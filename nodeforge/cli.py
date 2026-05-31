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
               mutate, synth, sandbox, differential, gate, nodegen, bank)


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


def run_author(ask, n=3, model="claude-sonnet-4-6", interactive=True,
               confirm_cb=None, approve_cb=None, max_spec_rounds=2,
               staging_root=None, force_bank=False, log=print, client=None):
    """Drive the full author loop. Returns a result dict:
       {status: banked|rejected|contradiction|ambiguity_exhausted|error,
        dest, spec, winner, report, ...}.

    confirm_cb(spec)->spec   : Stage-1 hook (auto mode). Defaults to confirm_mod.
    approve_cb(spec,cand,checks,unkilled)->True/RejectError : Stage-5 hook.
    """
    staging_root = staging_root or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_staging")

    # ---- Stage 0: elaborate ----
    log("[0] elaborating spec ...")
    spec, _u = spec_mod.elaborate(ask, model=model, client=client)

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
        outcome = differential.analyze(report, impl_ids, spec, candidates_by_id=by_id)
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
                        "question": outcome["question"]}
            log("    [AMBIGUITY] " + outcome["question"])
            # fold the clarification into the spec and re-run
            if confirm_cb is not None:
                # auto mode: append the question as an invariant the next round confirms
                spec.invariants.append("Resolve ambiguity: " + outcome["question"])
            else:
                ans = input("Clarify the intended behavior (becomes a new invariant): ").strip()
                if ans:
                    spec.invariants.append(ans)
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
    args = ap.parse_args(argv)

    interactive = not args.yes
    confirm_cb = None
    approve_cb = None
    if args.yes:
        confirm_cb = lambda s: (_set_confirmed(s))
        approve_cb = lambda *a, **k: True

    res = run_author(args.ask, n=args.n, model=args.model, interactive=interactive,
                     confirm_cb=confirm_cb, approve_cb=approve_cb, force_bank=args.force)
    print("\n=== RESULT ===")
    print(res["status"], "--", res.get("detail", res.get("dest", "")))
    return 0 if res["status"] == "banked" else 1


def _set_confirmed(spec):
    spec.confirmed = True
    return spec


if __name__ == "__main__":
    sys.exit(main())
