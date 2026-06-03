"""
v0.2 ambiguity-oracle LIVE gate -- the DEMOTED contract (spends API; embedded python;
NO bank side effect).

The ambiguity oracle is a demoted backstop: live testing showed elaborate already
resolves most under-specified asks by PARAMETERIZING
them into widgets (resize -> width/height node), so the oracle rarely fires and is
shipped as a SAFETY-NET BACKSTOP, not the headline. This gate therefore proves the
SAFE HALF only: across representative asks the oracle must NOT over-escalate -- every
one reaches a confident, bankable outcome. The escalation LOGIC itself (stance
divergence -> AMBIGUITY with options, and the duotone over-escalation guard) is proven
deterministically offline in tests/test_differential.py; it does not need live spend.

Runs Stage 0->4 (no bank, no resolve-loop) and asserts CONFIDENT for each:
  B   "resize smaller"   -> elaborate parameterizes (width/height) -> CONFIDENT
  CTL "invert colors"    -> fully specified -> CONFIDENT
  A   "duotone"          -> aesthetic look, no over-ask -> CONFIDENT

  python nodeforge/tests/oracle_live.py [B|CTL|A]   (default: all three)
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
from nodeforge import (cli, spec as spec_mod, codegen, mutate, synth,  # noqa: E402
                       differential as D)

ASKS = {
    "B":   "I want a node that resizes my image to make it smaller.",
    "CTL": "I want a node that inverts the colors of an image: output equals 1.0 minus the input.",
    "A":   ("I want a node that gives an image a duotone look -- map the whole image to a "
            "gradient between two colors based on how bright each pixel is."),
}
EXPECT = {"B": "CONFIDENT", "CTL": "CONFIDENT", "A": "CONFIDENT"}


def run_case(key, log):
    ask = ASKS[key]
    log(f"\n=== CASE {key}: {ask[:60]}...")
    spec, _u = spec_mod.elaborate(ask)
    axes = [a.get("axis") for a in spec.unpinned_axes if isinstance(a, dict)]
    log(f"  unpinned_axes surfaced: {axes or '(none)'}")
    spec.confirmed = True

    ref0, failing = cli._best_ref0(spec, "claude-sonnet-4-6", None, tries=4, log=log)
    if failing:
        return key, "contradiction", axes
    mutants = mutate.build_operator_mutants(spec, ref0.source, ref0.class_name)
    try:
        mutants += mutate.build_llm_mutants(spec, n=1)
    except Exception as e:
        log(f"  (llm mutant skipped: {e})")
    vet = synth.vet_battery(spec, ref0, mutants, log=log)
    kept = vet["kept_checks"]
    if not kept:
        return key, "no-checks", axes

    impls, _us = codegen.generate_impls(spec, n=3)
    stinfo = [(c.id, (c.stance or {}).get("interpretation")) for c in impls]
    log(f"  impls: {stinfo}")
    report = cli._run_vetted(spec, kept, impls)
    by_id = {c.id: c for c in impls}
    outcome = D.analyze_stance(report, [c.id for c in impls], spec, candidates_by_id=by_id)
    log(f"  -> {outcome['outcome']}: {outcome['detail']}")
    if outcome["outcome"] == D.AMBIGUITY:
        log(f"     options: {outcome.get('options')}")
    return key, outcome["outcome"], axes


def verdict(key, got):
    # Demoted contract: the safe half == no over-escalation. Every representative
    # ask must reach CONFIDENT (a bankable outcome), proving the oracle does not
    # falsely ask. The escalation path is proven offline in test_differential.py.
    return got == D.CONFIDENT


def main():
    keys = [sys.argv[1].upper()] if len(sys.argv) > 1 else ["B", "CTL", "A"]
    LOG = []
    log = lambda m: (LOG.append(str(m)), print(m))
    rows = []
    for k in keys:
        try:
            _, got, axes = run_case(k, log)
        except Exception as e:
            got, axes = f"ERROR:{type(e).__name__}:{e}", []
        ok = verdict(k, got)
        rows.append((k, EXPECT[k], got, ok, axes))
    out = ["", "=== ORACLE LIVE GATE ==="]
    allok = True
    for k, exp, got, ok, axes in rows:
        allok = allok and ok
        out.append(f"  {k}: expect={exp} got={got} axes={axes} -> {'OK' if ok else 'FAIL'}")
    out.append("ORACLE: " + ("PASS" if allok else "FAIL"))
    with open(os.path.join(_REPO, "_oracle_live.txt"), "w", encoding="ascii", errors="replace") as f:
        f.write("\n".join(LOG + out) + f"\nEXIT={0 if allok else 1}\n")
    print("\n".join(out))
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
