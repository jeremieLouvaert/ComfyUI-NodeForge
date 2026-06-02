"""
NodeForge sidebar-panel backend: aiohttp routes on ComfyUI's PromptServer + an
in-process worker thread that drives the proven `run_author()` engine, bridging
its three human-decision seams (confirm / ambiguity / approve) from `input()` to
HTTP-POST-backed `queue.Queue`s and streaming its `log=` progress over the
WebSocket ComfyUI already holds.

Design (plan: .claude/plans/curried-tinkering-nest.md):
  - The engine is reused VERBATIM. Only its callbacks change shape here.
  - Untrusted candidate code still execs ONLY in the sandbox subprocess (the
    engine spawns it regardless of where the engine runs). This module's thread
    runs trusted first-party orchestration + LLM calls; it is wrapped so an engine
    error becomes a `nodeforge:error` event, never a server crash.
  - custom_nodes is touched ONLY at the approved bank step (downstream of the
    blocking approve_cb). That invariant is structural, preserved here.

ALL heavy imports (the engine, anthropic, torch via sandbox, folder_paths) are
lazy inside handlers / the worker so importing this module at ComfyUI boot is
cheap and crash-proof. Routes register even with no API key (the engine only runs
on demand, and reports a clear error if the key is missing).
"""
import os
import json
import time
import queue
import threading
import traceback
import uuid

# --- register on ComfyUI's PromptServer; degrade to a no-op outside ComfyUI so a
#     static import smoke-test (and a broken boot) never crashes. -----------------
try:
    from aiohttp import web
    from server import PromptServer
    _SERVER = PromptServer.instance
    routes = _SERVER.routes
    _HAVE_SERVER = True
except Exception as _e:  # imported outside ComfyUI (tests) -> stub the decorators
    _HAVE_SERVER = False
    _SERVER = None

    class _StubRoutes:
        def _noop(self, *a, **k):
            def deco(fn):
                return fn
            return deco
        get = post = delete = put = _noop

    routes = _StubRoutes()
    web = None
    print(f"[NodeForge] server module unavailable ({_e}); routes are no-ops "
          f"(expected outside ComfyUI).")

VERSION = "0.2.0"
GATE_TIMEOUT = 600.0          # seconds a human gate (confirm/approve) may wait
AMBIGUITY_TIMEOUT = 300.0     # ambiguity is rarely surfaced; shorter wait
JOB_TTL = 1800.0             # GC a finished/idle job + its temp after this long
CANCEL = object()            # sentinel pushed into a job queue to cancel a wait


# ---------------------------------------------------------------------------
# job registry
# ---------------------------------------------------------------------------
_jobs = {}
_jobs_lock = threading.Lock()
_reaper_started = False


def _send(event, data, sid=None):
    """Thread-safe push to the originating tab (send_sync hops to the event loop
    via call_soon_threadsafe). No-op when there is no server (tests)."""
    if not _HAVE_SERVER:
        return
    try:
        _SERVER.send_sync(event, data, sid)
    except Exception as e:
        print(f"[NodeForge] send_sync({event}) failed: {e}")


def _temp_base():
    """ComfyUI temp dir (served by the built-in /view?type=temp). Lazy import."""
    import folder_paths
    return folder_paths.get_temp_directory()


class Job:
    """One author run + its three gate queues. Lives in `_jobs[job_id]`."""

    def __init__(self, ask, n, model, sid):
        self.id = uuid.uuid4().hex[:12]
        self.ask = ask
        self.n = n
        self.model = model
        self.sid = sid
        self.status = "starting"      # starting|running|awaiting|banked|rejected|exists|error|cancelled|aborted|contradiction|ambiguity_exhausted
        self.awaiting = None          # confirm|approval|ambiguity|None
        self.last_event = None        # (event, payload) -> resume-on-reopen
        self.log_lines = []
        self.result = None
        self.created = time.time()
        self.touched = time.time()
        self.confirm_q = queue.Queue(maxsize=1)
        self.ambiguity_q = queue.Queue(maxsize=1)
        self.approve_q = queue.Queue(maxsize=1)
        self.thread = None
        self.sub = f"nodeforge_{self.id}"      # subfolder under ComfyUI temp

    def touch(self):
        self.touched = time.time()

    def emit(self, event, payload, remember=True):
        payload = {"job_id": self.id, **payload}
        if remember:
            self.last_event = (event, payload)
        self.touch()
        _send(event, payload, self.sid)

    def snapshot(self):
        return {"job_id": self.id, "ask": self.ask, "status": self.status,
                "awaiting": self.awaiting,
                "last_event": self.last_event,
                "log": self.log_lines[-200:], "result": self.result}


class _Cancelled(Exception):
    pass


def _await(job, route_tag, event, payload, q, timeout, cancel_value):
    """Push an await_* event, block the worker thread on q, return the POSTed item.
    A CANCEL sentinel -> _Cancelled; a timeout -> cancel_value (caller decides)."""
    job.awaiting = route_tag
    job.status = "awaiting"
    job.emit(event, payload)
    try:
        item = q.get(timeout=timeout)
    except queue.Empty:
        job.awaiting = None
        return cancel_value
    job.awaiting = None
    job.status = "running"
    if item is CANCEL:
        raise _Cancelled()
    return item


# ---------------------------------------------------------------------------
# the worker: drive run_author with HTTP-queue-backed callbacks
# ---------------------------------------------------------------------------
def _img(subfolder, filename):
    """A /view?type=temp image descriptor the frontend turns into a URL."""
    return {"type": "temp", "subfolder": subfolder, "filename": filename}


def _run_job(job):
    """Outer guard: a worker thread must NEVER die silently. Any failure in the
    lazy imports / setup / engine becomes a visible nodeforge:error + a job
    snapshot detail (with a short trace), never a stuck 'starting' status."""
    try:
        _run_job_inner(job)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[NodeForge] job {job.id} worker crashed:\n{tb[-1800:]}")
        job.status = "error"
        job.result = {"status": "error", "detail": f"{type(e).__name__}: {e}",
                      "trace": tb[-1000:]}
        job.emit("nodeforge:error",
                 {"detail": f"{type(e).__name__}: {e}", "trace": tb[-1000:]})


def _run_job_inner(job):
    from . import cli, confirm as confirm_mod, gate as gate_mod
    base = _temp_base()
    job_root = os.path.join(base, job.sub)
    thumbs_dir = os.path.join(job_root, "thumbs")
    diff_dir = os.path.join(job_root, "diff")
    staging_root = os.path.join(job_root, "staging")

    # ---- log seam -> ws ----
    def ws_log(line):
        line = str(line)
        job.log_lines.append(line)
        job.emit("nodeforge:stage", {"line": line}, remember=False)

    # ---- Stage 1: confirm (render thumbs, push editable spec, block) ----
    def confirm_cb(spec):
        thumbs = {}
        try:
            thumbs = confirm_mod.render_input_thumbnails(spec, thumbs_dir)
        except Exception as e:
            ws_log(f"    (thumbnail render skipped: {e})")
        examples = []
        for e in spec.examples:
            ex = {"id": e.id, "nl_statement": e.nl_statement}
            if e.id in thumbs:
                ex["image"] = _img(f"{job.sub}/thumbs", f"in_{e.id}.png")
            examples.append(ex)
        payload = {"spec": spec.to_dict(), "examples": examples,
                   "title": spec.title, "ask": spec.ask,
                   "invariants": list(spec.invariants),
                   "unpinned_axes": list(spec.unpinned_axes)}
        edits = _await(job, "confirm", "nodeforge:await_confirm", payload,
                       job.confirm_q, GATE_TIMEOUT, cancel_value=CANCEL)
        if edits is CANCEL:
            raise confirm_mod.AbortError("confirm gate timed out")
        # edits = {"drop":[ids], "add_invariants":[str]} -> proven non-interactive path
        return confirm_mod.confirm_spec(spec, interactive=False, edits=edits or {})

    # ---- Stage 4: ambiguity (rarely fires; surface the real question) ----
    def ambiguity_cb(outcome):
        options = outcome.get("options", [])
        payload = {"question": outcome.get("question", ""),
                   "axis": outcome.get("axis", ""), "options": options}
        choice = _await(job, "ambiguity", "nodeforge:await_ambiguity", payload,
                        job.ambiguity_q, AMBIGUITY_TIMEOUT,
                        cancel_value=(options[0] if options else ""))
        return choice

    # ---- Stage 5: approval gate (the moat: code + test report + diff, block) ----
    def approve_cb(spec, winner, kept, unkilled, limited_verification=False, caveats=None):
        thumbs = {}
        try:
            thumbs = gate_mod.render_before_after(spec, winner, diff_dir)
        except Exception as e:
            ws_log(f"    (before/after render skipped: {e})")
        images = []
        for e in spec.examples:
            pair = {"example_id": e.id, "nl_statement": e.nl_statement}
            if f"in_{e.id}" in thumbs:
                pair["before"] = _img(f"{job.sub}/diff", f"in_{e.id}.png")
            if f"out_{e.id}" in thumbs:
                pair["after"] = _img(f"{job.sub}/diff", f"out_{e.id}.png")
            images.append(pair)
        checks = [{"name": c.name, "teeth": list(getattr(c, "teeth", []))} for c in kept]
        payload = {"title": spec.title, "class_name": winner.class_name,
                   "source": winner.source, "checks": checks,
                   "unkilled_mutants": list(unkilled or []), "images": images,
                   "limited_verification": bool(limited_verification),
                   "caveats": list(caveats or [])}
        decision = _await(job, "approval", "nodeforge:await_approval", payload,
                          job.approve_q, GATE_TIMEOUT, cancel_value=CANCEL)
        if decision is CANCEL:
            raise gate_mod.RejectError("approval gate timed out")
        if isinstance(decision, dict) and decision.get("decision") == "approve":
            return True
        reason = ""
        if isinstance(decision, dict):
            reason = decision.get("reason", "")
        raise gate_mod.RejectError(reason or "rejected at gate")

    # ---- drive the engine ----
    job.status = "running"
    try:
        res = cli.run_author(
            job.ask, n=job.n, model=job.model, interactive=False,
            confirm_cb=confirm_cb, approve_cb=approve_cb, ambiguity_cb=ambiguity_cb,
            precheck=False,            # the panel already ran /nodeforge/precheck
            staging_root=staging_root, log=ws_log,
        )
    except _Cancelled:
        job.status = "cancelled"
        job.emit("nodeforge:cancelled", {})
        return
    except confirm_mod.AbortError as e:
        job.status = "aborted"
        job.emit("nodeforge:error", {"detail": f"aborted: {e}"})
        return
    except Exception as e:
        job.status = "error"
        tb = traceback.format_exc()[-1200:]
        print(f"[NodeForge] job {job.id} crashed:\n{tb}")
        job.emit("nodeforge:error", {"detail": f"{type(e).__name__}: {e}"})
        return

    job.result = _result_summary(res)
    status = res.get("status", "error")
    job.status = status
    if status == "banked":
        live = _try_live_register(res)
        job.emit("nodeforge:banked", {**job.result, "live_registered": live})
    elif status == "rejected":
        job.emit("nodeforge:rejected", {"detail": res.get("detail", "")})
    elif status == "exists":
        job.emit("nodeforge:exists", job.result)
    else:  # contradiction | ambiguity_exhausted | error
        job.emit("nodeforge:error", {"status": status, "detail": res.get("detail", ""),
                                     **job.result})


def _result_summary(res):
    """JSON-safe subset of the engine result for the frontend / snapshot."""
    out = {"status": res.get("status")}
    for k in ("detail", "dest", "class_name", "display"):
        if res.get(k) is not None:
            out[k] = res[k]
    if res.get("limited_verification"):
        out["limited_verification"] = True
    if res.get("caveats"):
        out["caveats"] = list(res["caveats"])
    if res.get("unkilled_mutants"):
        out["unkilled_mutants"] = list(res["unkilled_mutants"])
    spec = res.get("spec")
    if spec is not None:
        try:
            out["title"] = spec.title
        except Exception:
            pass
    return out


def _try_live_register(res):
    """Pin #4 SPIKE seam. Default OFF (returns False -> frontend shows the restart
    CTA). The proven path is a one-click restart; live in-process registration is
    filled in + proven by the spike before being enabled by default."""
    return False


# ---------------------------------------------------------------------------
# reaper: GC finished / idle jobs and their temp dirs
# ---------------------------------------------------------------------------
def _reaper():
    import shutil
    while True:
        time.sleep(120)
        now = time.time()
        dead = []
        with _jobs_lock:
            for jid, job in list(_jobs.items()):
                idle = now - job.touched
                alive = job.thread is not None and job.thread.is_alive()
                if not alive and idle > JOB_TTL:
                    dead.append(jid)
            for jid in dead:
                _jobs.pop(jid, None)
        for jid in dead:
            try:
                shutil.rmtree(os.path.join(_temp_base(), f"nodeforge_{jid}"),
                              ignore_errors=True)
            except Exception:
                pass


def _ensure_reaper():
    global _reaper_started
    if _reaper_started:
        return
    _reaper_started = True
    threading.Thread(target=_reaper, name="nodeforge-reaper", daemon=True).start()


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
async def _json_body(request):
    try:
        return await request.json()
    except Exception:
        return {}


@routes.post("/nodeforge/ping")
async def nf_ping(request):
    return web.json_response({"ok": True, "version": VERSION,
                              "jobs": len(_jobs)})


@routes.post("/nodeforge/precheck")
async def nf_precheck(request):
    """Three-band retrieval router as a pre-step. Degrades to band=low on failure
    so authoring is never blocked."""
    body = await _json_body(request)
    ask = (body.get("ask") or "").strip()
    if not ask:
        return web.json_response({"error": "empty ask"}, status=400)
    model = body.get("model") or "claude-sonnet-4-6"
    import asyncio
    from functools import partial
    from . import precheck as precheck_mod
    loop = asyncio.get_event_loop()

    def _run():
        try:
            return precheck_mod.find_existing(ask, model=model, log=lambda *a, **k: None)
        except Exception as e:
            print(f"[NodeForge] precheck failed: {e}")
            return {"band": "low", "hit": None, "candidates": []}

    routed = await loop.run_in_executor(None, _run)
    return web.json_response(routed)


@routes.post("/nodeforge/jobs")
async def nf_create_job(request):
    body = await _json_body(request)
    ask = (body.get("ask") or "").strip()
    if not ask:
        return web.json_response({"error": "empty ask"}, status=400)
    n = int(body.get("n", 3))
    model = body.get("model") or "claude-sonnet-4-6"
    sid = body.get("clientId") or getattr(request, "rel_url", None) and \
        request.rel_url.query.get("clientId")
    _ensure_reaper()
    job = Job(ask, n, model, sid)
    with _jobs_lock:
        _jobs[job.id] = job
    job.thread = threading.Thread(target=_run_job, args=(job,),
                                  name=f"nodeforge-job-{job.id}", daemon=True)
    job.thread.start()
    return web.json_response({"job_id": job.id})


def _get_job(request):
    return _jobs.get(request.match_info.get("id"))


def _resolve_gate(job, tag, q, value):
    """Hand a decision to a worker blocked on a gate. 409 if not awaiting it."""
    if job.awaiting != tag:
        return web.json_response(
            {"error": f"job not awaiting {tag} (awaiting={job.awaiting})"}, status=409)
    try:
        q.put_nowait(value)
    except queue.Full:
        return web.json_response({"error": "gate already resolved"}, status=409)
    return web.json_response({"ok": True})


@routes.post("/nodeforge/jobs/{id}/confirm")
async def nf_confirm(request):
    job = _get_job(request)
    if not job:
        return web.json_response({"error": "no such job"}, status=404)
    body = await _json_body(request)
    edits = {"drop": list(body.get("drop", [])),
             "add_invariants": list(body.get("add_invariants", []))}
    return _resolve_gate(job, "confirm", job.confirm_q, edits)


@routes.post("/nodeforge/jobs/{id}/ambiguity")
async def nf_ambiguity(request):
    job = _get_job(request)
    if not job:
        return web.json_response({"error": "no such job"}, status=404)
    body = await _json_body(request)
    choice = body.get("choice", "")
    return _resolve_gate(job, "ambiguity", job.ambiguity_q, choice)


@routes.post("/nodeforge/jobs/{id}/approve")
async def nf_approve(request):
    job = _get_job(request)
    if not job:
        return web.json_response({"error": "no such job"}, status=404)
    body = await _json_body(request)
    decision = body.get("decision", "reject")
    return _resolve_gate(job, "approval", job.approve_q,
                         {"decision": decision, "reason": body.get("reason", "")})


@routes.get("/nodeforge/jobs/{id}")
async def nf_get_job(request):
    job = _get_job(request)
    if not job:
        return web.json_response({"error": "no such job"}, status=404)
    return web.json_response(job.snapshot())


@routes.delete("/nodeforge/jobs/{id}")
async def nf_cancel_job(request):
    job = _get_job(request)
    if not job:
        return web.json_response({"error": "no such job"}, status=404)
    # unblock a worker parked on whichever gate it is awaiting
    for tag, q in (("confirm", job.confirm_q), ("approval", job.approve_q),
                   ("ambiguity", job.ambiguity_q)):
        if job.awaiting == tag:
            try:
                q.put_nowait(CANCEL)
            except queue.Full:
                pass
    job.status = "cancelled"
    return web.json_response({"ok": True})


@routes.post("/nodeforge/jobs/{id}/restart")
async def nf_restart(request):
    """Honest pin-#4 fallback: re-exec the ComfyUI process so a freshly-banked node
    appears. Mirrors ComfyUI-Manager's reboot. The frontend reloads the page."""
    import sys
    job = _get_job(request)
    _send("nodeforge:restarting", {"job_id": job.id if job else None})

    def _reboot():
        time.sleep(0.5)
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            print(f"[NodeForge] restart failed: {e}")

    threading.Thread(target=_reboot, name="nodeforge-reboot", daemon=True).start()
    return web.json_response({"ok": True, "restarting": True})


if _HAVE_SERVER:
    print(f"[NodeForge] panel routes registered (/nodeforge/*) v{VERSION}")
