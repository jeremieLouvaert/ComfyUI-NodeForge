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


# ---------------------------------------------------------------------------
# v0.2 divergent-stance ambiguity oracle (additive -- analyze() is unchanged).
#
# The v0.1 B-FAIL: an ambiguous ask banked one reading because temperature-only
# impls CONVERGED, so analyze() saw agreement -> CONFIDENT. The oracle forces
# stance-directed impls to diverge along a model-flagged unpinned axis. But
# escalating on ANY digest divergence re-breaks case A: two valid impls can pass
# the battery yet differ in qhash on midtones (a value wobble) -> false ambiguity.
# So escalation is SCOPED: it fires only when two passers carry DIFFERENT
# interpretations of the SAME flagged axis AND diverge on that axis's DECLARED
# dimension (a shape diff for a resize-class axis, not a qhash wobble). Non-stance
# runs (no Candidate carries a .stance) delegate verbatim to analyze().
# ---------------------------------------------------------------------------
def _divergence_dimension(da, db):
    """Classify HOW two per-example digest lists differ. Returns a subset of
    {"shape","channel","dtype","value"}. Pure over the existing _child._digest
    output (list of per-output dicts with shape/dtype/min/mean/max/qhash)."""
    dims = set()
    da = da or []
    db = db or []
    if len(da) != len(db):
        dims.add("shape")            # different output arity -> structural
    for oa, ob in zip(da, db):
        if not (isinstance(oa, dict) and isinstance(ob, dict)):
            if oa != ob:
                dims.add("value")
            continue
        sa, sb = oa.get("shape"), ob.get("shape")
        if sa != sb:
            dims.add("shape")
            # last-dim-only difference on an otherwise equal shape == a channel-count change
            if (isinstance(sa, list) and isinstance(sb, list) and len(sa) == len(sb)
                    and sa[:-1] == sb[:-1] and sa[-1:] != sb[-1:]):
                dims.add("channel")
        if oa.get("dtype") != ob.get("dtype"):
            dims.add("dtype")
        for k in ("min", "mean", "max", "qhash"):
            if oa.get(k) != ob.get(k):
                dims.add("value")
    return dims


def _stance_pairs(passers, candidates_by_id):
    """Yield (a, b, stance_a) for passer pairs that take DIFFERENT interpretations
    of the SAME flagged axis. Pairs with no/identical stance are skipped."""
    cb = candidates_by_id or {}
    for i, a in enumerate(passers):
        for b in passers[i + 1:]:
            sa = getattr(cb.get(a), "stance", None)
            sb = getattr(cb.get(b), "stance", None)
            if not (sa and sb):
                continue
            if sa.get("axis") != sb.get("axis"):
                continue
            if sa.get("interpretation") == sb.get("interpretation"):
                continue
            yield a, b, sa


def _stance_ambiguity(report, passers, candidates_by_id):
    """Return {axis, dimension, fixture, interpretations} iff some different-stance
    passer pair diverges ON THE FLAGGED AXIS'S DIMENSION on a confirmed-example
    fixture; else None. A divergence on any OTHER dimension (e.g. a qhash wobble
    when the flagged axis is 'shape') is NOT ambiguity -- the over-escalation guard."""
    for a, b, sa in _stance_pairs(passers, candidates_by_id):
        dim = sa.get("dimension")
        fixtures = list(report.output_digests.get(a, {}).keys())
        for fx in fixtures:
            dims = _divergence_dimension(report.output_digests.get(a, {}).get(fx),
                                         report.output_digests.get(b, {}).get(fx))
            if dim in dims:
                axis = sa.get("axis")
                seen, interps = set(), []
                for cid in passers:
                    st = getattr((candidates_by_id or {}).get(cid), "stance", None)
                    if st and st.get("axis") == axis:
                        it = st.get("interpretation")
                        if it and it not in seen:
                            seen.add(it)
                            interps.append(it)
                return {"axis": axis, "dimension": dim, "fixture": fx,
                        "interpretations": interps}
    return None


def _structured_question(amb):
    """A multiple-choice clarification sourced from the flagged axis interpretations."""
    opts = amb.get("interpretations", [])
    lines = [f"Your request is ambiguous on '{amb.get('axis','this')}' and your confirmed "
             f"examples don't decide it. NodeForge built working nodes for each reading; "
             f"they differ. Which did you mean?"]
    for i, o in enumerate(opts, 1):
        lines.append(f"  ({i}) {o}")
    return "\n".join(lines)


def analyze_stance(report, impl_ids, spec, candidates_by_id=None):
    """Stance-aware Stage-4 outcome. For non-stance runs (no Candidate carries a
    .stance) this is byte-identical to analyze(). For stance runs it escalates to
    AMBIGUITY only on axis-attributable, on-dimension divergence (see module note);
    the AMBIGUITY result additionally carries {axis, options} for the structured
    clarification UX. Non-passer outcomes reuse analyze() verbatim."""
    cb = candidates_by_id or {}
    has_stance = any(getattr(cb.get(cid), "stance", None) for cid in impl_ids)
    if not has_stance:
        return analyze(report, impl_ids, spec, candidates_by_id)

    passers = [cid for cid in impl_ids if report.verdict(cid) == "pass"]
    if not passers:
        # contradiction / retry logic is identical to the base analyzer
        return analyze(report, impl_ids, spec, candidates_by_id)

    amb = _stance_ambiguity(report, passers, cb)
    if amb is None:
        winner = _pick_winner(passers, cb)
        return {"outcome": CONFIDENT, "winner_id": winner, "passers": passers,
                "question": None, "axis": None, "options": [],
                "detail": f"{len(passers)} stance implementation(s) passed and agree on "
                          f"every flagged axis dimension."}
    return {"outcome": AMBIGUITY, "winner_id": None, "passers": passers,
            "question": _structured_question(amb),
            "axis": amb["axis"], "options": amb["interpretations"],
            "detail": f"stance implementations diverge on the unpinned axis "
                      f"'{amb['axis']}' (dimension={amb['dimension']}, fixture "
                      f"'{amb['fixture']}') -> ask the human."}
