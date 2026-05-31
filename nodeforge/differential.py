"""
Stage 4 -- differential consensus + triage (escalating-oracle layer 5).

Given the vetted battery (Stage 2) run against the N Stage-3 implementations in
the sandbox, decide the outcome. Pure logic on a RunReport + the spec's example
coverage -- no torch, no LLM.

Anti-circularity rule 4: divergence on UNCONFIRMED behavior is a QUESTION for the
human, never a majority vote (a majority can share a blind spot).

Outcomes:
  CONFIDENT     -- >=1 impl passes the whole battery and all battery-passers AGREE
                   on every confirmed-example fixture. Winner is chosen.
  AMBIGUITY     -- battery-passers DIVERGE on a fixture no confirmed example pins
                   down -> escalate to Stage 1 with a targeted question.
  CONTRADICTION -- no impl passes and >=2 checks fail on EVERY impl (mutually
                   exclusive constraints) -> do not bank.
  RETRY         -- no impl passes but failures look scattered -> widen N.
"""
CONFIDENT = "confident"
AMBIGUITY = "ambiguity"
CONTRADICTION = "contradiction"
RETRY = "retry"


def _agree(report, a_id, b_id):
    da = report.output_digests.get(a_id, {})
    db = report.output_digests.get(b_id, {})
    keys = set(da) | set(db)
    if not keys:
        return True
    return all(da.get(k) == db.get(k) for k in keys)


def _common_failing_checks(report, impl_ids):
    per_impl = {}
    for cid in impl_ids:
        per_impl[cid] = {r.check_name for r in report.results_for(cid) if not r.passed}
    common = None
    for s in per_impl.values():
        common = s if common is None else (common & s)
    return common or set()


def _pick_winner(passers, candidates_by_id):
    if not candidates_by_id:
        return passers[0]
    def key(cid):
        c = candidates_by_id.get(cid)
        temp = (c.temperature if c and c.temperature is not None else 1.0)
        size = len(c.source) if c else 0
        return (temp, size)
    return sorted(passers, key=key)[0]


def _flat(digest):
    if not digest:
        return ()
    out = []
    for d in digest:
        if isinstance(d, dict):
            out.append(tuple(sorted((k, str(v)) for k, v in d.items())))
        else:
            out.append(str(d))
    return tuple(out)


def _ambiguity_question(report, passers, spec):
    fixtures = list(report.output_digests.get(passers[0], {}).keys())
    diverge_fixture = None
    for fx in fixtures:
        vals = {_flat(report.output_digests.get(cid, {}).get(fx)) for cid in passers}
        if len(vals) > 1:
            diverge_fixture = fx
            break
    topic = ""
    if spec.edge_cases:
        topic = " Possibly related to: " + "; ".join(spec.edge_cases[:2])
    base = ("The implementations agree on every confirmed example but produce "
            "DIFFERENT results on a case the spec did not pin down")
    if diverge_fixture:
        base += f" (fixture '{diverge_fixture}')"
    return (base + ". This is genuine ambiguity, not a bug. Please clarify the intended "
            "behavior so it can become a confirmed example." + topic)


def analyze(report, impl_ids, spec, candidates_by_id=None):
    """Decide the Stage-4 outcome. Returns
    {outcome, winner_id, passers, question, detail}."""
    passers = [cid for cid in impl_ids if report.verdict(cid) == "pass"]
    errored = [cid for cid in impl_ids if report.verdict(cid) == "error"]

    if passers:
        ref = passers[0]
        disagree = [cid for cid in passers[1:] if not _agree(report, ref, cid)]
        if not disagree:
            winner = _pick_winner(passers, candidates_by_id)
            return {"outcome": CONFIDENT, "winner_id": winner, "passers": passers,
                    "question": None,
                    "detail": f"{len(passers)} implementation(s) passed the battery and agree."}
        q = _ambiguity_question(report, passers, spec)
        return {"outcome": AMBIGUITY, "winner_id": None, "passers": passers,
                "question": q,
                "detail": f"{len(passers)} implementations pass the battery but disagree "
                          f"on behavior the spec left open."}

    common = _common_failing_checks(report, impl_ids)
    if len(common) >= 2:
        return {"outcome": CONTRADICTION, "winner_id": None, "passers": [],
                "question": None,
                "detail": "No implementation can satisfy the confirmed checks; these "
                          "fail on every implementation: " + ", ".join(sorted(common)[:6])}
    return {"outcome": RETRY, "winner_id": None, "passers": [],
            "question": None,
            "detail": f"No implementation passed (errored={len(errored)}); failures look "
                      f"scattered -- widen N or regenerate."}
