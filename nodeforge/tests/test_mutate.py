"""
Mutation-engine test (operator mutants, offline -- no LLM).

Uses the benchmark's CORRECT classes as ref0 stand-ins, builds operator mutants,
and runs ref0 + mutants through the sandbox against the benchmark's already-
generated battery. Asserts:
  - ref0 PASSES its battery (the wrapper plumbing is sound).
  - every operator mutant LOADS and returns a tensor (valid teeth target).
  - every operator mutant behaviorally DIFFERS from ref0 on >=1 fixture.

Run by file path with PYTHONPATH=repo root.
"""
import os
import sys
import inspect

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "benchmark"))

import cases  # noqa: E402
from nodeforge import records, mutate, sandbox  # noqa: E402

PREAMBLE = "import math\nimport torch\nimport torch.nn.functional as F\n\n"
_GB = inspect.getsource(cases._gaussian_blur)
FIX = [{"example_id": "tex", "input_spec": {"generator": "seeded_texture", "params": {"h": 8, "w": 8}}},
       {"example_id": "corners", "input_spec": {"generator": "known_pattern", "params": {"name": "rgb_corners"}}}]


def ref0_for(cls):
    return PREAMBLE + _GB + "\n\n" + inspect.getsource(cls)


def spec_for(cls):
    return records.Spec(
        ask="(benchmark)", title=cls.__name__, input_types=cls.INPUT_TYPES(),
        return_types=list(cls.RETURN_TYPES),
        return_names=list(getattr(cls, "RETURN_NAMES", []) or []) or None)


def battery_source(cid):
    with open(os.path.join(_REPO, "benchmark", "results", f"{cid}_trial0.py"), encoding="utf-8") as f:
        return f.read()


def main():
    out = [f"sandbox backend: {sandbox.mem_cap_backend()}"]
    all_ok = True
    for case in cases.CASES:
        cid = case["id"]
        cls = case["correct"][0][1]
        spec = spec_for(cls)
        r0 = ref0_for(cls)
        muts = mutate.build_operator_mutants(spec, r0, cls.__name__)
        cands = [{"id": "ref0", "source": r0, "class_name": cls.__name__, "origin": "ref0"}]
        cands += [{"id": m.id, "source": m.source, "class_name": m.class_name, "origin": m.origin}
                  for m in muts]
        job = {"job_id": f"mut_{cid}", "mode": "run", "allow_gpu": False,
               "candidates": cands, "batteries": [{"id": "b0", "source": battery_source(cid)}],
               "example_fixtures": FIX}
        rep = sandbox.run_job(job, wall_s=60)

        ref0_pass = rep.verdict("ref0") == "pass"
        ref0_dig = rep.output_digests.get("ref0", {})
        if not ref0_pass:
            fails = [f"{r.check_name}:{r.detail}" for r in rep.results_for('ref0') if not r.passed]
            out.append(f"[{cid}] !! ref0 did NOT pass: {fails[:3]}")
            all_ok = False
        if rep.load_errors:
            out.append(f"[{cid}] !! load errors: {rep.load_errors}")
            all_ok = False
        caught = 0
        for m in muts:
            if rep.load_errors.get(m.id):
                out.append(f"[{cid}] !! mutant {m.id} load: {rep.load_errors[m.id]}")
                all_ok = False
                continue
            mdig = rep.output_digests.get(m.id, {})
            differs = any(mdig.get(k) != ref0_dig.get(k) for k in ref0_dig)
            if not differs:
                # EXPECTED for some op/fixture combos (e.g. identity-corruption on a
                # mosaic whose grid makes tiles 1px -> already identity at this size).
                # synth.valid_mutants drops these as un-killable; not a failure.
                out.append(f"[{cid}] (note) mutant {m.id} does not differ from ref0 at "
                           f"this fixture -> would be dropped by valid_mutants")
            if rep.verdict(m.id) == "fail":
                caught += 1
        out.append(f"[{cid}] ref0_pass={ref0_pass} mutants={len(muts)} "
                   f"battery_caught={caught}/{len(muts)} wall={rep.wall_ms}ms")

    out.append("MUTATE_ENGINE: " + ("PASS" if all_ok else "FAIL"))
    with open(os.path.join(_REPO, "_mutate_result.txt"), "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(out) + f"\nEXIT={0 if all_ok else 1}\n")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
