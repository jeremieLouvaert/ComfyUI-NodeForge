"""
NodeForge v0.1 AUTHOR-branch CLI -- wires Stage 0 -> 5.

  nodeforge "I want a node that ..."   [--n 3] [--model ...] [--yes]

Flow: elaborate spec (0) -> human confirms (1) -> generate+example-filter ref0,
build mutants, vet a battery via the ref0 teeth-gate (2) -> generate N impls (3)
-> run the vetted battery vs the impls in the sandbox + differential consensus
(4) -> human-approval gate + bank (5). On Stage-4 AMBIGUITY the targeted question
is folded into the spec as a new invariant and the loop re-runs (bounded).

run_author() is the importable entry the scripted acceptance test drives with
non-interactive confirm/approve callbacks.
"""
import os
import sys
import argparse

from . import (records, spec as spec_mod, confirm as confirm_mod, codegen,
               mutate, synth, sandbox, differential, gate, nodegen, bank,
               precheck as precheck_mod)


# ---------------------------------------------------------------------------
# Stage 4 helper: run the vetted battery (list[Check]) vs impl candidates
# ---------------------------------------------------------------------------
def _run_vetted(spec, kept_checks, impl_candidates, wall_s=90):
    batteries = [{"id": f"k{i}", "source": c.source} for i, c in enumerate(kept_checks)]
    cands = [{"id": c.id, "source": c.source, "class_name": c.class_name, "origin": c.origin}
             for c in impl_candidates]
    fixtures = [{"example_id": e.id, "input_spec": e.input_spec.to_dict()} for e in spec.examples]
    job = {"job_id": "stage4", "mode": "run", "allow_gpu": False,
           "candidates": cands, "batteries": batteries, "example_fixtures": fixtures}
    return sandbox.run_job(job, wall_s=wall_s)


def _best_ref0(spec, model, client, tries=4, log=print):
    """Generate up to `tries` ref0 draws; return (best_ref0, failing_examples).
    failing_examples is [] iff some draw satisfied ALL confirmed examples (that draw
    is returned). Otherwise returns the draw with the fewest failures + its
    remaining failures (caller decides contradiction)."""
    best = None
    best_fail = None
    for i in range(tries):
        ref0, _u = codegen.generate_ref0(spec, model=model, client=client)
        ok, failing = synth.ref0_satisfies_examples(spec, ref0)
        if ok:
            return ref0, []
        if best_fail is None or len(failing) < len(best_fail):
            best, best_fail = ref0, failing
        log(f"    ref0 draw {i+1} failed examples {failing}; retrying")
    return best, best_fail


def _resolve_ambiguity(spec, outcome, confirm_cb, log):
    """Fold a Stage-4 ambiguity resolution into the spec, then let the loop re-run.

    Structured (the v0.2 oracle, outcome carries `options`): the human picks one
    interpretation via a multiple-choice menu; it becomes a hard invariant AND the
    resolved axis is removed from spec.unpinned_axes so the next round stops probing
    it (impls converge on the pinned reading -> CONFIDENT -> bank). In auto mode
    (confirm_cb set, no human) the first option is chosen deterministically so the
    loop still progresses. Falls back to today's free-text path when no options."""
    axis = outcome.get("axis")
    options = outcome.get("options", [])
    if options:
        if confirm_cb is not None:
            choice = options[0]            # auto mode: deterministic, keeps the loop moving
        else:
            choice = confirm_mod.ask_choice(outcome["question"], options)
        spec.invariants.append(f"The '{axis}' MUST be: {choice}")
        # stop re-probing the now-resolved axis next round
        spec.unpinned_axes = [a for a in spec.unpinned_axes
                              if not (isinstance(a, dict) and a.get("axis") == axis)]
        log(f"    [AMBIGUITY resolved] {axis} -> {choice}")
        return
    # free-text fallback (no structured options)
    if confirm_cb is not None:
        spec.invariants.append("Resolve ambiguity: " + outcome["question"])
    else:
        ans = input("Clarify the intended behavior (becomes a new invariant): ").strip()
        if ans:
            spec.invariants.append(ans)


def run_author(ask, n=3, model="claude-sonnet-4-6", interactive=True,
               confirm_cb=None, approve_cb=None, max_spec_rounds=2,
               staging_root=None, force_bank=False, log=print, client=None,
               precheck=True, precheck_cb=None):
    """Drive the full author loop. Returns a result dict:
       {status: banked|rejected|contradiction|ambiguity_exhausted|exists|error,
        dest, spec, winner, report, ...}.

    confirm_cb(spec)->spec   : Stage-1 hook (auto mode). Defaults to confirm_mod.
    approve_cb(spec,cand,checks,unkilled)->True/RejectError : Stage-5 hook.
    precheck_cb(hit)->bool   : pre-check hook; True = author anyway, False = stop.
    """
    staging_root = staging_root or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_staging")

    # ---- Pre-check (v0.1.1): does an existing pack already do this? ----
    # Advisory only -- never auto-installs, never auto-suppresses authoring.
    # Needs a human to confirm, so it runs only when interactive (or a cb drives it).
    if precheck and (interactive or precheck_cb is not None):
        hit = precheck_mod.find_existing(ask, model=model, client=client, log=log)
        if hit:
            author_anyway = (precheck_cb(hit) if precheck_cb is not None
                             else precheck_mod.prompt_existing(hit))
            if not author_anyway:
                return {"status": "exists", "ask": ask, "pack": hit,
                        "detail": f"existing pack suggested: {hit['title']} ({hit['url']})"}

    # ---- Stage 0: elaborate ----
    log("[0] elaborating spec ...")
    spec, _u = spec_mod.elaborate(ask, model=model, client=client)

    # Each unpinned axis can cost one resolution round (the oracle probes one axis
    # per round); give the loop enough budget to resolve them all + a final bank
    # round, so a multi-axis spec is not starved into ambiguity_exhausted.
    max_spec_rounds = max(max_spec_rounds, len(spec.unpinned_axes) + 1)

    rounds = 0
    while True:
        rounds += 1
        # ---- Stage 1: human confirms ----
        log("[1] confirm spec")
        if confirm_cb is not None:
            spec = confirm_cb(spec)
        else:
            spec = confirm_mod.confirm_spec(spec, interactive=interactive,
                                            render_dir=os.path.join(staging_root, "thumbs"))

        # ---- Stage 2: ref0 + mutants + teeth-gated battery ----
        log("[2] generating ref0 + vetting battery (teeth-gate) ...")
        # Try several ref0 draws; keep the one satisfying the MOST confirmed
        # examples. A single draw is occasionally imperfect on one example; that is
        # not a contradiction. Only if NO draw across the budget can satisfy the
        # examples do we treat the spec as bad/contradictory.
        ref0, failing = _best_ref0(spec, model, client, tries=4, log=log)
        if failing:
            log(f"    no ref0 satisfied all examples; best still fails: {failing}")
            return {"status": "contradiction", "spec": spec,
                    "detail": f"no reference impl can satisfy the confirmed examples "
                              f"after multiple tries: {failing}"}
        mutants = mutate.build_operator_mutants(spec, ref0.source, ref0.class_name)
        try:
            mutants += mutate.build_llm_mutants(spec, n=1, model=model, client=client)
        except Exception as e:
            log(f"    (LLM mutant skipped: {e})")
        vet = synth.vet_battery(spec, ref0, mutants, model=model, client=client, log=log)
        kept = vet["kept_checks"]
        if not kept:
            return {"status": "error", "spec": spec,
                    "detail": "Stage 2 produced no teeth-passing checks."}
        if vet["unkilled_mutants"]:
            log(f"    residual: {len(vet['unkilled_mutants'])} mutation class(es) uncaught "
                f"-> surfaced at the gate")

        # ---- Stage 3: N implementations ----
        log(f"[3] generating {n} implementations ...")
        impls, _us = codegen.generate_impls(spec, n=n, model=model, client=client)

        # ---- Stage 4: run vetted battery + differential ----
        log("[4] running battery vs implementations + differential ...")
        report = _run_vetted(spec, kept, impls)
        impl_ids = [c.id for c in impls]
        by_id = {c.id: c for c in impls}
        # analyze_stance is byte-identical to analyze for non-stance runs (no
        # Candidate carries a .stance); for stance runs it escalates only on
        # axis-attributable, on-dimension divergence (the v0.2 ambiguity oracle).
        outcome = differential.analyze_stance(report, impl_ids, spec, candidates_by_id=by_id)
        log(f"    outcome: {outcome['outcome']} -- {outcome['detail']}")

        if outcome["outcome"] == differential.CONTRADICTION:
            return {"status": "contradiction", "spec": spec, "report": report,
                    "detail": outcome["detail"]}
        if outcome["outcome"] == differential.RETRY:
            if rounds >= max_spec_rounds:
                return {"status": "error", "spec": spec, "report": report,
                        "detail": "no implementation passed after retries: " + outcome["detail"]}
            log("    retrying with fresh implementations ...")
            continue
        if outcome["outcome"] == differential.AMBIGUITY:
            if rounds >= max_spec_rounds:
                return {"status": "ambiguity_exhausted", "spec": spec, "report": report,
                        "question": outcome["question"], "axis": outcome.get("axis"),
                        "options": outcome.get("options", [])}
            log("    [AMBIGUITY] " + outcome["question"])
            _resolve_ambiguity(spec, outcome, confirm_cb, log)
            spec.confirmed = False
            continue

        # CONFIDENT
        winner = by_id[outcome["winner_id"]]
        log(f"[5] approval gate (winner: {winner.id})")
        try:
            if approve_cb is not None:
                approve_cb(spec, winner, kept, vet["unkilled_mutants"])
            else:
                gate.approve(spec, winner, kept, vet["unkilled_mutants"],
                             render_dir=os.path.join(staging_root, "diff"),
                             interactive=interactive)
        except gate.RejectError as e:
            return {"status": "rejected", "spec": spec, "winner": winner, "detail": str(e)}

        # ---- bank ----
        node_src, class_name = nodegen.build_node_source(spec, winner)
        ok, err = bank.loadtest_pack(node_src, class_name)
        if not ok:
            return {"status": "error", "spec": spec, "winner": winner,
                    "detail": f"banked load-test failed pre-copy: {err}"}
        pack_dir, class_name, display = nodegen.write_pack(spec, winner, staging_root,
                                                          class_name=class_name)
        dest, msg = bank.bank(pack_dir, force=force_bank)
        log(msg)
        return {"status": "banked", "spec": spec, "winner": winner, "dest": dest,
                "class_name": class_name, "display": display, "report": report,
                "kept_checks": kept, "unkilled_mutants": vet["unkilled_mutants"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="NodeForge -- author a ComfyUI node from a description.")
    ap.add_argument("ask", help="what you want the node to do")
    ap.add_argument("--n", type=int, default=3, help="number of implementations (default 3)")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--yes", action="store_true", help="non-interactive: auto-confirm + auto-approve")
    ap.add_argument("--force", action="store_true", help="overwrite an existing banked pack")
    ap.add_argument("--no-precheck", action="store_true",
                    help="skip the 'does this already exist?' retrieval pre-check")
    args = ap.parse_args(argv)

    interactive = not args.yes
    confirm_cb = None
    approve_cb = None
    if args.yes:
        confirm_cb = lambda s: (_set_confirmed(s))
        approve_cb = lambda *a, **k: True

    res = run_author(args.ask, n=args.n, model=args.model, interactive=interactive,
                     confirm_cb=confirm_cb, approve_cb=approve_cb, force_bank=args.force,
                     precheck=not args.no_precheck)
    print("\n=== RESULT ===")
    print(res["status"], "--", res.get("detail", res.get("dest", "")))
    # 'exists' is a success: the user chose to install an existing pack instead.
    return 0 if res["status"] in ("banked", "exists") else 1


def _set_confirmed(spec):
    spec.confirmed = True
    return spec


if __name__ == "__main__":
    sys.exit(main())
