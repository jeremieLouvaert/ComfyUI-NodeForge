"""
Sandbox parity test (the independent check, with teeth).

Proves nodeforge.sandbox is behavior-identical to the proven benchmark harness:
take the batteries the benchmark ALREADY generated (benchmark/results/*_trial0.py)
and run them, through the subprocess sandbox, against the correct + broken
implementations from benchmark/cases.py. The verdicts must match what
run_benchmark.py found: every correct impl PASSES (specificity) and every broken
impl is CAUGHT (teeth).

The negative control IS built in: if the sandbox were toothless (e.g. it marked
everything pass), the broken impls would slip and this test fails.

Run with the embedded python:
  F:\...\python_embeded\python.exe -m nodeforge.tests.test_sandbox_parity
"""
import os
import sys
import inspect

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "benchmark"))

import cases  # noqa: E402  (benchmark/cases.py)
from nodeforge import sandbox  # noqa: E402

PREAMBLE = "import math\nimport torch\nimport torch.nn.functional as F\n\n"
_GB_SRC = inspect.getsource(cases._gaussian_blur)


def candidate_source(cls):
    """Self-contained source for one node class: preamble + the shared gaussian
    helper + the class itself (so unsharp variants that call _gaussian_blur work)."""
    return PREAMBLE + _GB_SRC + "\n\n" + inspect.getsource(cls)


def battery_source(case_id):
    path = os.path.join(_REPO, "benchmark", "results", f"{case_id}_trial0.py")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def run_case(case):
    cid = case["id"]
    candidates = []
    for label, cls in case["correct"]:
        candidates.append({"id": f"correct::{label}", "source": candidate_source(cls),
                           "class_name": cls.__name__, "origin": "impl"})
    for label, cls in case["broken"]:
        candidates.append({"id": f"broken::{label}", "source": candidate_source(cls),
                           "class_name": cls.__name__, "origin": "impl"})
    job = {"job_id": f"parity_{cid}", "mode": "run",
           "allow_gpu": False, "candidates": candidates,
           "batteries": [{"id": "b0", "source": battery_source(cid)}],
           "example_fixtures": []}
    report = sandbox.run_job(job, wall_s=60, mem_mb=4096)
    return report


def main():
    print(f"sandbox memory-cap backend: {sandbox.mem_cap_backend()}")
    print(f"embedded python: {sandbox.EMBEDDED_PYTHON}\n")
    spec_total = spec_pass = teeth_total = teeth_caught = 0
    failures = []
    for case in cases.CASES:
        cid = case["id"]
        rep = run_case(case)
        if rep.load_errors:
            print(f"[{cid}] LOAD ERRORS: {rep.load_errors}")
        if rep.stderr_tail:
            # only show a short hint; full battery noise is expected on stderr
            pass
        for label, _ in case["correct"]:
            cid_key = f"correct::{label}"
            v = rep.verdict(cid_key)
            spec_total += 1
            ok = v == "pass"
            spec_pass += int(ok)
            if not ok:
                fails = [f"{r.check_name}: {r.detail}" for r in rep.results_for(cid_key) if not r.passed]
                failures.append(f"[{cid}] FALSE REJECTION {label}: {fails[:3]}")
        for label, _ in case["broken"]:
            cid_key = f"broken::{label}"
            v = rep.verdict(cid_key)
            teeth_total += 1
            caught = v == "fail"
            teeth_caught += int(caught)
            if not caught:
                failures.append(f"[{cid}] SLIP (broken passed) {label}")
        print(f"[{cid}] checks ran; correct={len(case['correct'])} broken={len(case['broken'])} "
              f"wall={rep.wall_ms}ms")

    print("\n" + "#" * 60)
    print(f"SPECIFICITY (correct accepted): {spec_pass}/{spec_total}")
    print(f"TEETH       (broken caught)   : {teeth_caught}/{teeth_total}")
    for f in failures:
        print("  !! " + f)
    ok = (spec_pass == spec_total and teeth_caught == teeth_total and spec_total > 0)
    print("PARITY: " + ("PASS -- sandbox matches benchmark verdicts" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
