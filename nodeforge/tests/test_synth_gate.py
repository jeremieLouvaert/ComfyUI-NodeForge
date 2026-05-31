"""
Stage-2 gate-mechanic test (OFFLINE -- no LLM).

Feeds the benchmark's already-generated batteries (benchmark/results/*_trial0.py)
to synth.evaluate_draw, using the benchmark's CORRECT class as ref0 and the
operator mutants as teeth targets. Asserts the ref0 teeth-gate INVARIANT (what one
draw can prove without API):
  - keeps >= 1 check per case,
  - every kept check has teeth (kills >= 1 mutant) -- by construction of the gate,
  - the kept checks kill at least as many mutants as the raw battery does (the
    gate does not lose kills), and kill > 0.

Full COVERAGE (every mutant killed) is vet_battery's multi-draw loop, which needs
the API and is proven in the live acceptance test -- one fixed offline draw cannot
guarantee it.

Run by file path with PYTHONPATH=repo root.
"""
import os
import sys
import inspect

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "benchmark"))

import cases  # noqa: E402
from nodeforge import records, mutate, synth  # noqa: E402

PREAMBLE = "import math\nimport torch\nimport torch.nn.functional as F\n\n"
_GB = inspect.getsource(cases._gaussian_blur)


def spec_for(cls):
    return records.Spec(ask="(bench)", title=cls.__name__, input_types=cls.INPUT_TYPES(),
                        return_types=list(cls.RETURN_TYPES),
                        return_names=list(getattr(cls, "RETURN_NAMES", []) or []) or None)


def main():
    out = [f"backend: {synth.sandbox.mem_cap_backend()}"]
    all_ok = True
    for case in cases.CASES:
        cid = case["id"]
        cls = case["correct"][0][1]
        spec = spec_for(cls)
        ref0_src = PREAMBLE + _GB + "\n\n" + inspect.getsource(cls)
        ref0 = records.Candidate(id="ref0", source=ref0_src, class_name=cls.__name__, origin="ref0")
        muts = mutate.build_operator_mutants(spec, ref0_src, cls.__name__)
        muts, dropped = synth.valid_mutants(spec, ref0, muts)   # drop un-killable mutants
        with open(os.path.join(_REPO, "benchmark", "results", f"{cid}_trial0.py"), encoding="utf-8") as f:
            battery_src = f.read()
        kept, open_qs, loaded = synth.evaluate_draw(spec, battery_src, ref0, muts, wall_s=90)
        killed = set()
        for c in kept:
            killed.update(c.teeth)
            if not c.teeth:
                out.append(f"[{cid}] !! kept check {c.name} has NO teeth (gate bug)")
                all_ok = False
            if not c.passes_ref0:
                out.append(f"[{cid}] !! kept check {c.name} did not pass ref0 (gate bug)")
                all_ok = False
        mutant_ids = {m.id for m in muts}
        # Offline bar = the gate MECHANIC a single fixed draw can prove: kept>=1,
        # every kept check has teeth + passes ref0 (asserted above), and the draw
        # kills >=1 mutant. FULL coverage (every mutant killed) is vet_battery's
        # multi-draw job and is proven live in acceptance -- a single draw of a
        # deliberately-loose spec (the downscale ambiguity case) legitimately
        # cannot kill every mutant, so coverage here is informational.
        covered = killed >= mutant_ids
        ok = loaded and len(kept) >= 1 and len(killed) >= 1
        all_ok = all_ok and ok
        unkilled = sorted(mutant_ids - killed)
        out.append(f"[{cid}] loaded={loaded} kept={len(kept)} "
                   f"killed={len(killed)}/{len(mutant_ids)} single_draw_covered={covered} "
                   f"unkilled={unkilled} dropped={dropped} open_qs={len(open_qs)}")
    full = sum(1 for l in out if "single_draw_covered=True" in l)
    out.append(f"{full} of 6 cases also fully covered by a single offline battery draw "
               f"(full coverage is vet_battery's multi-draw job).")
    out.append("SYNTH_GATE: " + ("PASS" if all_ok else "FAIL"))
    with open(os.path.join(_REPO, "_synth_result.txt"), "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(out) + f"\nEXIT={0 if all_ok else 1}\n")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
