"""
Stage-4 differential logic test (OFFLINE -- synthetic RunReports, no LLM/torch).
Asserts the four outcomes: CONFIDENT, AMBIGUITY, CONTRADICTION, RETRY.
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
from nodeforge import records, differential as D


def mk(results, digests, load_errors=None):
    rs = [records.CheckResult(check_name=c, candidate_id=cid, passed=p)
          for (c, cid, p) in results]
    return records.RunReport(job_id="t", results=rs, output_digests=digests,
                             load_errors=load_errors or {})


def spec():
    return records.Spec(ask="x", title="X", input_types={"required": {"image": ["IMAGE"]}},
                        return_types=["IMAGE"], edge_cases=["interpolation method unspecified"])


def main():
    out = []
    s = spec()

    # CONFIDENT: both impls pass all checks and agree on fixtures
    rep = mk([("c1", "i0", True), ("c1", "i1", True)],
             {"i0": {"e1": [{"mean": 0.5}]}, "i1": {"e1": [{"mean": 0.5}]}})
    r = D.analyze(rep, ["i0", "i1"], s)
    out.append(("CONFIDENT", r["outcome"] == D.CONFIDENT and r["winner_id"] in ("i0", "i1")))

    # AMBIGUITY: both pass all checks but DISAGREE on the fixture digest
    rep = mk([("c1", "i0", True), ("c1", "i1", True)],
             {"i0": {"e1": [{"mean": 0.3}]}, "i1": {"e1": [{"mean": 0.7}]}})
    r = D.analyze(rep, ["i0", "i1"], s)
    out.append(("AMBIGUITY", r["outcome"] == D.AMBIGUITY and bool(r["question"])))

    # CONTRADICTION: nobody passes; >=2 checks fail on every impl
    rep = mk([("cA", "i0", False), ("cB", "i0", False),
              ("cA", "i1", False), ("cB", "i1", False)],
             {"i0": {}, "i1": {}})
    r = D.analyze(rep, ["i0", "i1"], s)
    out.append(("CONTRADICTION", r["outcome"] == D.CONTRADICTION))

    # RETRY: nobody passes but failures are scattered (1 distinct failing check each)
    rep = mk([("cA", "i0", False), ("cB", "i0", True),
              ("cA", "i1", True), ("cB", "i1", False)],
             {"i0": {}, "i1": {}})
    r = D.analyze(rep, ["i0", "i1"], s)
    out.append(("RETRY", r["outcome"] == D.RETRY))

    ok = all(p for _, p in out)
    lines = [f"{name}: {'OK' if p else 'FAIL'}" for name, p in out]
    lines.append("DIFFERENTIAL: " + ("PASS" if ok else "FAIL"))
    with open(os.path.join(_REPO, "_diff_result.txt"), "w", encoding="ascii") as f:
        f.write("\n".join(lines) + f"\nEXIT={0 if ok else 1}\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
