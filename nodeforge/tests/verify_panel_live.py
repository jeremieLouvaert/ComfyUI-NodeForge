"""
Live end-to-end verification of the NodeForge sidebar-panel BACKEND, driven over
HTTP exactly as the React frontend drives it -- no browser needed. Run this AFTER
restarting ComfyUI with the pack installed (custom_nodes/ComfyUI-NodeForge).

It proves the panel backend e2e:
  ping -> precheck -> create job -> (stream) -> confirm gate -> [ambiguity] ->
  approval gate (asserts the gate payload carries the generated code + a real
  before/after diff) -> approve -> banked (asserts the pack landed on disk).

Usage (embedded python):
  python -m nodeforge.tests.verify_panel_live ["an ask"] [--host 127.0.0.1:8188]

Costs Anthropic API (one full author run, ~$1), same as acceptance.py. Uses only
stdlib (urllib) so it runs under the embedded python with no extra deps.
"""
import os
import sys
import json
import time
import urllib.request

HOST = os.environ.get("NODEFORGE_HOST", "127.0.0.1:8188")
# A genuinely-novel, collision-unlikely ask (channel swap has no built-in and is
# fast to author + verify). Override via argv[1].
DEFAULT_ASK = "swap the red and blue channels of the image"
POLL_S = 2.0
JOB_TIMEOUT_S = 360.0


def _post(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(f"http://{HOST}{path}", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read().decode())


def _get(path):
    req = urllib.request.Request(f"http://{HOST}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read().decode())


def _fail(msg):
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    ask = DEFAULT_ASK
    if argv and not argv[0].startswith("--"):
        ask = argv[0]
    print(f"=== NodeForge panel live verify @ {HOST} ===")
    print(f"ask: {ask!r}\n")

    # 1) ping
    st, pong = _post("/nodeforge/ping")
    if not (st == 200 and pong.get("ok")):
        _fail(f"ping failed: {st} {pong}")
    print(f"[1] ping OK -> v{pong.get('version')} ({pong.get('jobs')} jobs)")

    # 2) precheck (one cheap rerank call; any band is fine -- just prove the route)
    st, routed = _post("/nodeforge/precheck", {"ask": ask})
    if st != 200 or "band" not in routed:
        _fail(f"precheck failed: {st} {routed}")
    print(f"[2] precheck OK -> band={routed['band']} "
          f"hit={(routed.get('hit') or {}).get('title')}")

    # 3) create job (precheck=False inside the job; this is the author path)
    st, created = _post("/nodeforge/jobs", {"ask": ask, "clientId": "verify-panel"})
    job_id = created.get("job_id")
    if st != 200 or not job_id:
        _fail(f"job create failed: {st} {created}")
    print(f"[3] job created -> {job_id}")

    # 4) drive the gates by polling GET /jobs/{id} (the frontend uses ws; polling
    #    the same snapshot is equivalent for a headless driver).
    t0 = time.time()
    confirmed = approved = False
    approval_payload = None
    last_log_n = 0
    status = None
    while True:
        if time.time() - t0 > JOB_TIMEOUT_S:
            _fail(f"job timed out after {JOB_TIMEOUT_S}s (status={status})")
        st, snap = _get(f"/nodeforge/jobs/{job_id}")
        if st != 200:
            _fail(f"snapshot failed: {st} {snap}")
        status = snap.get("status")
        awaiting = snap.get("awaiting")
        # echo new log lines
        log = snap.get("log", [])
        for line in log[last_log_n:]:
            print(f"    | {line}")
        last_log_n = len(log)

        if awaiting == "confirm" and not confirmed:
            st, r = _post(f"/nodeforge/jobs/{job_id}/confirm",
                          {"drop": [], "add_invariants": []})
            print(f"[4a] confirm gate -> POST confirm {r}")
            confirmed = True
        elif awaiting == "ambiguity":
            le = snap.get("last_event") or [None, {}]
            opts = (le[1] or {}).get("options", [])
            choice = opts[0] if opts else ""
            _post(f"/nodeforge/jobs/{job_id}/ambiguity", {"choice": choice})
            print(f"[4b] ambiguity gate -> chose {choice!r}")
        elif awaiting == "approval" and not approved:
            le = snap.get("last_event") or [None, {}]
            approval_payload = le[1] or {}
            # TEETH: the moat gate must carry the generated code + a real diff.
            src = approval_payload.get("source", "")
            imgs = approval_payload.get("images", [])
            has_diff = any(i.get("before") and i.get("after") for i in imgs)
            if "class" not in src.lower():
                _fail("approval payload missing generated source code")
            if not has_diff:
                _fail(f"approval payload missing a before/after diff: {imgs}")
            print(f"[4c] approval gate -> class={approval_payload.get('class_name')} | "
                  f"checks={len(approval_payload.get('checks', []))} | "
                  f"unkilled={approval_payload.get('unkilled_mutants')} | "
                  f"diff_images={sum(1 for i in imgs if i.get('before') and i.get('after'))}")
            st, r = _post(f"/nodeforge/jobs/{job_id}/approve", {"decision": "approve"})
            print(f"     -> POST approve {r}")
            approved = True

        if status in ("banked", "rejected", "error", "exists", "contradiction",
                      "ambiguity_exhausted", "cancelled", "aborted"):
            break
        time.sleep(POLL_S)

    # 5) terminal assertions
    print(f"\n[5] terminal status: {status}")
    result = snap.get("result") or {}
    if status != "banked":
        _fail(f"expected banked, got {status} -- {result.get('detail', snap)}")
    dest = result.get("dest")
    if not dest or not os.path.isdir(dest):
        _fail(f"banked but dest missing on disk: {dest}")
    files = os.listdir(dest)
    print(f"    banked -> {dest}")
    print(f"    pack files: {files}")
    if "__init__.py" not in files:
        _fail("banked pack has no __init__.py")
    print("\n[PASS] NodeForge panel backend e2e: ping -> precheck -> author -> "
          "confirm -> approval(code+diff) -> approve -> banked-on-disk.")
    print("       (Browser UI + install->appears are yours to eyeball; pin-#4 "
          "live-register is OFF by default -> restart CTA.)")


if __name__ == "__main__":
    main()
