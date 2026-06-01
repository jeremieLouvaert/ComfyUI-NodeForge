"""
Stage-4 differential logic test (OFFLINE -- synthetic RunReports, no LLM/torch).
Asserts the four base outcomes (CONFIDENT, AMBIGUITY, CONTRADICTION, RETRY) AND
the v0.2 stance oracle (analyze_stance): scoped on-dimension escalation, the
duotone over-escalation guard, and byte-identical delegation for non-stance runs.
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


def stance_cand(cid, interp, axis="target size", dim="shape"):
    """A passing stance-tagged Candidate for analyze_stance tests."""
    return records.Candidate(id=cid, source="x" * 100, class_name="N", origin="stance",
                             temperature=0.5,
                             stance={"axis": axis, "interpretation": interp, "dimension": dim})


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

    # ---- v0.2 stance oracle (analyze_stance) -----------------------------
    # Helper: a full IMAGE per-output digest so divergence dims are unambiguous.
    def dg(shape, mean, qh):
        return [{"shape": shape, "dtype": "torch.float32",
                 "min": 0.0, "mean": mean, "max": 1.0, "qhash": qh}]

    # REGRESSION: with NO stance tags, analyze_stance == analyze on all 4 cases.
    for name, results, digests in [
        ("reg-confident", [("c1", "i0", True), ("c1", "i1", True)],
         {"i0": {"e1": dg([1, 4, 4, 3], 0.5, 11)}, "i1": {"e1": dg([1, 4, 4, 3], 0.5, 11)}}),
        ("reg-ambiguity", [("c1", "i0", True), ("c1", "i1", True)],
         {"i0": {"e1": dg([1, 4, 4, 3], 0.3, 7)}, "i1": {"e1": dg([1, 4, 4, 3], 0.7, 9)}}),
        ("reg-contradiction", [("cA", "i0", False), ("cB", "i0", False),
                               ("cA", "i1", False), ("cB", "i1", False)], {"i0": {}, "i1": {}}),
        ("reg-retry", [("cA", "i0", False), ("cB", "i0", True),
                       ("cA", "i1", True), ("cB", "i1", False)], {"i0": {}, "i1": {}}),
    ]:
        rep = mk(results, digests)
        base = D.analyze(rep, ["i0", "i1"], s)
        st = D.analyze_stance(rep, ["i0", "i1"], s)   # no candidates_by_id -> no stance
        out.append((f"STANCE {name} delegates", base["outcome"] == st["outcome"]))

    # B-ESCALATES: two different-interpretation passers diverge on the SHAPE
    # dimension (the flagged axis dimension) -> AMBIGUITY with options populated.
    cands = {"i0": stance_cand("i0", "half (0.5x)", dim="shape"),
             "i1": stance_cand("i1", "fixed 512 long edge", dim="shape")}
    rep = mk([("c1", "i0", True), ("c1", "i1", True)],
             {"i0": {"e1": dg([1, 2, 2, 3], 0.5, 5)}, "i1": {"e1": dg([1, 512, 512, 3], 0.5, 6)}})
    r = D.analyze_stance(rep, ["i0", "i1"], s, candidates_by_id=cands)
    out.append(("STANCE B-escalates", r["outcome"] == D.AMBIGUITY
                and len(r.get("options", [])) == 2 and r.get("axis") == "target size"))

    # A-BANKS / OFF-DIMENSION (duotone guard): axis dimension is SHAPE, but the two
    # passers differ ONLY in value (mean+qhash) at the SAME shape -> NOT on the
    # flagged dimension -> CONFIDENT. This is the regression the feature must not break.
    rep = mk([("c1", "i0", True), ("c1", "i1", True)],
             {"i0": {"e1": dg([1, 4, 4, 3], 0.42, 7)}, "i1": {"e1": dg([1, 4, 4, 3], 0.55, 9)}})
    r = D.analyze_stance(rep, ["i0", "i1"], s, candidates_by_id=cands)
    out.append(("STANCE A-banks (off-dim value wobble)", r["outcome"] == D.CONFIDENT
                and r["winner_id"] in ("i0", "i1")))

    # CONTROL: a value-dimension axis ("kernel type") whose passers produce EQUAL
    # digests on flat fixtures -> no divergence at all -> CONFIDENT.
    vc = {"i0": stance_cand("i0", "gaussian", axis="kernel", dim="value"),
          "i1": stance_cand("i1", "box", axis="kernel", dim="value")}
    rep = mk([("c1", "i0", True), ("c1", "i1", True)],
             {"i0": {"e1": dg([1, 4, 4, 3], 0.5, 11)}, "i1": {"e1": dg([1, 4, 4, 3], 0.5, 11)}})
    r = D.analyze_stance(rep, ["i0", "i1"], s, candidates_by_id=vc)
    out.append(("STANCE control (equal digests)", r["outcome"] == D.CONFIDENT))

    # VALUE-DIM ESCALATE: a genuinely value-dimension axis whose passers diverge in
    # value -> AMBIGUITY (proves the dimension match is symmetric, not shape-only).
    rep = mk([("c1", "i0", True), ("c1", "i1", True)],
             {"i0": {"e1": dg([1, 4, 4, 3], 0.30, 7)}, "i1": {"e1": dg([1, 4, 4, 3], 0.70, 9)}})
    r = D.analyze_stance(rep, ["i0", "i1"], s, candidates_by_id=vc)
    out.append(("STANCE value-dim escalates", r["outcome"] == D.AMBIGUITY))

    ok = all(p for _, p in out)
    lines = [f"{name}: {'OK' if p else 'FAIL'}" for name, p in out]
    lines.append("DIFFERENTIAL: " + ("PASS" if ok else "FAIL"))
    with open(os.path.join(_REPO, "_diff_result.txt"), "w", encoding="ascii") as f:
        f.write("\n".join(lines) + f"\nEXIT={0 if ok else 1}\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
