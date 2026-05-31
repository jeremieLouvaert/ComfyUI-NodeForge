"""
Sandbox CHILD -- runs inside an isolated subprocess (the embedded python).

This is the ONLY first-party file that execs candidate node code and imports
torch. It reads one job as JSON on stdin, runs the requested mode, and prints
exactly one RunReport JSON object on stdout. Everything else (logs, torch
warnings) goes to stderr so stdout stays a clean single JSON document.

Threat model (self-verification-model.md 9.3): buggy / accidentally-destructive
code, NOT hardened RCE. Defenses here: a loud socket guard (catches accidental
network use), determinism, and -- enforced by the PARENT -- a Job-Object memory
cap + wall-clock kill. On Windows this is not a hard security boundary; the real
boundary is "no live ComfyUI server until the human approves the bank".

Job (stdin) schema:
  {
    "job_id": str,
    "mode": "run" | "loadtest",
    "allow_gpu": bool,
    "candidates": [{"id","source","class_name","origin"}],
    "batteries":  [{"id","source"}],            # mode=="run"; each is a full
                                                #   generated module with CHECKS
                                                #   (+ optional OPEN_QUESTIONS)
    "example_fixtures": [{"example_id","input_spec"}],   # for output digests
  }

Each battery is exec'd as a WHOLE module (so its CHECKS can rely on module-level
helpers/imports) exactly like benchmark/run_benchmark.load_battery. A result's
check_name is "<battery_id>:<fn_name>" so per-check provenance survives.

Stdout: one RunReport dict (records.RunReport.to_dict()), with an extra
"open_questions" map {battery_id: [str]} for triage.

load_battery / run_one_check semantics are copied from benchmark/run_benchmark.py
verbatim (a raised check counts as failed) so the sandbox is behavior-identical
to the proven benchmark harness.
"""
import sys
import os
import json
import time
import traceback

# The ComfyUI embedded python ignores PYTHONPATH (a python._pth file disables it),
# so make `nodeforge` importable from inside the child by putting the repo root
# (two dirs up from this file) on sys.path ourselves. Must happen before any
# `from nodeforge import ...`.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# accidental-network guard (NOT a security boundary; catches accidents loudly)
# ---------------------------------------------------------------------------
def _install_socket_guard():
    import socket

    class _BlockedSocket(socket.socket):
        def __init__(self, *a, **k):
            raise OSError("network access is blocked in the NodeForge sandbox")

    socket.socket = _BlockedSocket
    try:
        import urllib.request as _u
        def _blocked(*a, **k):
            raise OSError("network access is blocked in the NodeForge sandbox")
        _u.urlopen = _blocked
    except Exception:
        pass


def _load_class(source, class_name):
    """Exec a candidate's source in a fresh namespace and return the class."""
    ns = {"__name__": "nf_candidate"}
    exec(compile(source, f"<candidate:{class_name}>", "exec"), ns)
    if class_name not in ns:
        # tolerate the model naming the class differently: take the first class
        # that has the ComfyUI node shape.
        for v in ns.values():
            if isinstance(v, type) and hasattr(v, "INPUT_TYPES") and hasattr(v, "RETURN_TYPES"):
                return v
        raise KeyError(f"class {class_name!r} not defined and no node-shaped class found")
    return ns[class_name]


def _load_battery(battery_id, source):
    """Exec a whole generated battery module and return (checks, open_questions).

    Mirrors benchmark/run_benchmark.load_battery: the module defines CHECKS (a
    list of check functions) and optionally OPEN_QUESTIONS, and may rely on its
    own module-level helpers/imports. Returns [(qualified_name, fn)], [open_qs]."""
    ns = {"__name__": f"nf_battery_{battery_id}"}
    exec(compile(source, f"<battery:{battery_id}>", "exec"), ns)
    checks = ns.get("CHECKS")
    if not isinstance(checks, list) or not checks:
        raise ValueError("battery did not define a non-empty CHECKS list")
    open_qs = ns.get("OPEN_QUESTIONS", [])
    if not isinstance(open_qs, list):
        open_qs = [str(open_qs)]
    named = []
    for fn in checks:
        fname = getattr(fn, "__name__", "check")
        named.append((f"{battery_id}:{fname}", fn))
    return named, open_qs


def _run_one_check(name, fn, NodeClass):
    """Run a single check. A raise == failed. (benchmark/run_benchmark semantics.)"""
    try:
        res = fn(NodeClass)
        if isinstance(res, (tuple, list)) and len(res) >= 2:
            rname = str(res[0])
            passed = bool(res[1])
            detail = str(res[2]) if len(res) > 2 else ""
            return rname, passed, detail, False
        return name, False, f"bad return: {res!r}", False
    except Exception as e:
        return name, False, f"raised {type(e).__name__}: {e}", True


def _call_node(NodeClass, image, args=None):
    """Instantiate and call the node on a single IMAGE, filling other required
    inputs from `args` where provided, else from INPUT_TYPES defaults. Returns the
    raw output tuple."""
    args = args or {}
    node = NodeClass()
    fn = getattr(node, NodeClass.FUNCTION)
    spec = NodeClass.INPUT_TYPES()
    kwargs = {}
    req = spec.get("required", {})
    for pname, pdef in req.items():
        if pname == "image" or (isinstance(pdef, (list, tuple)) and pdef and pdef[0] == "IMAGE"):
            kwargs[pname] = image
        elif pname in args:
            kwargs[pname] = args[pname]
        else:
            kwargs[pname] = _default_for(pdef)
    return fn(**kwargs)


def _default_for(pdef):
    """Pull a widget default from an INPUT_TYPES entry, else a type fallback."""
    if isinstance(pdef, (list, tuple)) and pdef:
        tname = pdef[0]
        opts = pdef[1] if len(pdef) > 1 and isinstance(pdef[1], dict) else {}
        if "default" in opts:
            return opts["default"]
        if tname == "INT":
            return int(opts.get("min", 1) or 1)
        if tname == "FLOAT":
            return float(opts.get("min", 0.5) or 0.5)
        if tname == "BOOLEAN":
            return False
        if isinstance(tname, (list, tuple)) and tname:   # combo
            return tname[0]
    return None


def _digest(out_tuple):
    """A stable, lossy-but-discriminating digest of a node's output tuple.

    Per output: (shape, dtype, rounded min/mean/max, 16x16 quantized hash).
    Two impls 'agree' iff digests match on every example fixture. The 16x16
    quantized per-pixel hash defends against min/mean/max collisions."""
    import torch
    parts = []
    items = out_tuple if isinstance(out_tuple, (tuple, list)) else (out_tuple,)
    for t in items:
        if not torch.is_tensor(t):
            parts.append({"nontensor": repr(t)[:80]})
            continue
        tf = t.detach().float().cpu()
        d = {"shape": list(t.shape), "dtype": str(t.dtype),
             "min": round(float(tf.min()), 4) if tf.numel() else 0.0,
             "mean": round(float(tf.mean()), 4) if tf.numel() else 0.0,
             "max": round(float(tf.max()), 4) if tf.numel() else 0.0}
        # quantized thumbnail hash: reduce to <=16x16, 8-bit quantize, hash
        x = tf
        if x.ndim == 4:
            x = x[0]
        if x.ndim == 3 and x.shape[-1] in (1, 3):
            x = x.permute(2, 0, 1)          # C,H,W
        elif x.ndim == 2:
            x = x.unsqueeze(0)              # 1,H,W (mask)
        if x.ndim == 3:
            import torch.nn.functional as F
            x = x.unsqueeze(0)
            h, w = x.shape[-2], x.shape[-1]
            th, tw = min(16, h), min(16, w)
            if h > 16 or w > 16:
                x = F.adaptive_avg_pool2d(x, (th, tw))
            q = (x.clamp(0, 1) * 255).round().to(torch.uint8).flatten().tolist()
            d["qhash"] = hash(tuple(q)) & 0xFFFFFFFF
        parts.append(d)
    return parts


def main():
    # Candidate code + torch import may print; keep stdout clean for the one JSON
    # document by routing everything to stderr until we emit the final report.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr

    raw = sys.stdin.read()
    job = json.loads(raw)
    job_id = job.get("job_id", "?")
    report = {"job_id": job_id, "results": [], "output_digests": {},
              "load_errors": {}, "open_questions": {}, "timed_out": False, "oom": False,
              "stderr_tail": "", "wall_ms": 0, "peak_rss_mb": 0}
    t0 = time.time()

    def emit(r):
        sys.stdout = real_stdout
        print(json.dumps(r))
        sys.stdout.flush()

    _install_socket_guard()
    import torch
    torch.manual_seed(0)
    try:
        torch.use_deterministic_algorithms(True, warn_only=True)
    except Exception:
        pass

    candidates = job.get("candidates", [])
    batteries_spec = job.get("batteries", [])
    fixtures = job.get("example_fixtures", [])
    mode = job.get("mode", "run")
    report["open_questions"] = {}

    # load batteries once (mode run). A battery that fails to load is recorded
    # (the orchestrator regenerates it) but does not abort the whole job.
    loaded_checks = []   # [(qualified_name, fn)]
    if mode == "run":
        for bat in batteries_spec:
            bid = bat["id"]
            try:
                named, open_qs = _load_battery(bid, bat["source"])
                loaded_checks.extend(named)
                report["open_questions"][bid] = open_qs
            except Exception as e:
                report["load_errors"][f"battery:{bid}"] = f"{type(e).__name__}: {e}"
        if not loaded_checks:
            report["stderr_tail"] = "no battery produced a usable CHECKS list"
            emit(report); return

    # build example fixtures once
    from nodeforge import fixtures as fx
    built = {}
    for f in fixtures:
        try:
            built[f["example_id"]] = (fx.build(f["input_spec"]), f.get("args", {}))
        except Exception as e:
            report["stderr_tail"] += f"fixture {f.get('example_id')} build failed: {e}\n"

    for cand in candidates:
        cid = cand["id"]
        try:
            cls = _load_class(cand["source"], cand["class_name"])
        except Exception as e:
            report["load_errors"][cid] = f"{type(e).__name__}: {e}"
            continue

        if mode == "loadtest":
            # structural sanity only (layers 1): has the node shape + runs once
            try:
                assert hasattr(cls, "INPUT_TYPES") and hasattr(cls, "RETURN_TYPES")
                assert isinstance(cls.RETURN_TYPES, (tuple, list))
                assert isinstance(cls.FUNCTION, str)
                img = fx.build({"generator": "seeded_texture", "params": {"h": 8, "w": 8}})
                _call_node(cls, img)
            except Exception as e:
                report["load_errors"][cid] = f"loadtest: {type(e).__name__}: {e}"
            continue

        # mode run: every check x this candidate. Use the battery-qualified id
        # as the canonical check_name (the generated check's own returned name is
        # folded into the detail so provenance + human label both survive).
        for qname, fn in loaded_checks:
            rname, passed, detail, raised = _run_one_check(qname, fn, cls)
            report["results"].append({"check_name": qname, "candidate_id": cid,
                                      "passed": passed,
                                      "detail": (f"[{rname}] " + detail)[:300], "raised": raised})
        # output digests on each example fixture (using that example's args)
        dig = {}
        for ex_id, (img, ex_args) in built.items():
            try:
                out = _call_node(cls, img, ex_args)
                dig[ex_id] = _digest(out)
            except Exception as e:
                dig[ex_id] = [{"error": f"{type(e).__name__}: {e}"}]
        report["output_digests"][cid] = dig

    report["wall_ms"] = int((time.time() - t0) * 1000)
    emit(report)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # last-resort: main() redirects stdout to stderr, so restore it here.
        sys.stdout = sys.__stdout__
        print(json.dumps({"job_id": "?", "results": [], "output_digests": {},
                          "load_errors": {}, "open_questions": {},
                          "timed_out": False, "oom": False,
                          "stderr_tail": f"child crashed: {type(e).__name__}: {e}\n"
                                         f"{traceback.format_exc()[-1000:]}",
                          "wall_ms": 0, "peak_rss_mb": 0}))
