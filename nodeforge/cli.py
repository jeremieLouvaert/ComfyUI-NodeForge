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


# A trivial always-pass battery used only to make the sandbox load + run the impls
# (so we learn which ones are runnable + get output digests) when there are no real
# checks at all -- the advisory posture never lets "no checks" become a dead-end.
_NOOP_CHECK = records.Check(
    name="_noop",
    source="def check_noop(NodeClass):\n    return ('noop', True, '')\nCHECKS=[check_noop]\nOPEN_QUESTIONS=[]\n",
    teeth=[], passes_ref0=True, vacuous=True)


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


def _resolve_ambiguity(spec, outcome, confirm_cb, log, ambiguity_cb=None):
    """Fold a Stage-4 ambiguity resolution into the spec, then let the loop re-run.

    Structured (the v0.2 oracle, outcome carries `options`): the human picks one
    interpretation via a multiple-choice menu; it becomes a hard invariant AND the
    resolved axis is removed from spec.unpinned_axes so the next round stops probing
    it (impls converge on the pinned reading -> CONFIDENT -> bank). Resolution order:
    an explicit `ambiguity_cb` (the panel surfaces the question to the human) wins;
    else in auto mode (confirm_cb set, no human) the first option is chosen
    deterministically so the loop still progresses; else the interactive CLI menu.
    Falls back to a free-text path when no options."""
    axis = outcome.get("axis")
    options = outcome.get("options", [])
    if options:
        if ambiguity_cb is not None:
            choice = ambiguity_cb(outcome)         # panel: surface the real question
            if choice not in options:              # honor the human-question contract,
                choice = options[0]                # but never let a bad return derail it
        elif confirm_cb is not None:
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
    if ambiguity_cb is not None:
        ans = (ambiguity_cb(outcome) or "").strip()
        if ans:
            spec.invariants.append(ans)
    elif confirm_cb is not None:
        spec.invariants.append("Resolve ambiguity: " + outcome["question"])
    else:
        ans = input("Clarify the intended behavior (becomes a new invariant): ").strip()
        if ans:
            spec.invariants.append(ans)


def run_author(ask, n=3, model="claude-sonnet-4-6", interactive=True,
               confirm_cb=None, approve_cb=None, max_spec_rounds=2,
               staging_root=None, force_bank=False, log=print, client=None,
               precheck=True, precheck_cb=None, ambiguity_cb=None):
    """Drive the full author loop. Returns a result dict:
       {status: banked|rejected|contradiction|ambiguity_exhausted|exists|error,
        dest, spec, winner, report, ...}.

    confirm_cb(spec)->spec   : Stage-1 hook (auto mode). Defaults to confirm_mod.
    approve_cb(spec,cand,checks,unkilled)->True/RejectError : Stage-5 hook.
    precheck_cb(routed)->bool: pre-check hook; receives the routed band result
                               ({band, hit, candidates}); True = author anyway,
                               False = stop (use what retrieval found).
    ambiguity_cb(outcome)->str: Stage-4 hook; given the ambiguity outcome (carries
                               `question`/`axis`/`options`), returns the chosen
                               interpretation string. When set, the loop surfaces
                               the question instead of auto-picking options[0] (the
                               panel's human-question contract). Default None keeps
                               today's behavior.
    """
    staging_root = staging_root or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_staging")

    # ---- Pre-check (v0.2): three-band retrieval router. ----
    # Advisory only -- never auto-installs, never auto-suppresses authoring.
    # Needs a human, so it runs only when interactive (or a cb drives it).
    #   core/high -> recommend the built-in/pack; default is still "author anyway".
    #   middle    -> show 1-3 related packs AND offer to author; the human picks.
    #   low       -> say nothing, author.
    if precheck and (interactive or precheck_cb is not None):
        routed = precheck_mod.find_existing(ask, model=model, client=client, log=log)
        band = routed.get("band", "low")
        if precheck_cb is not None:
            # programmatic hook: receives the full routed result, returns
            # True=author anyway / False=stop (the user uses what we found).
            if band != "low" and not precheck_cb(routed):
                return {"status": "exists", "ask": ask, "routed": routed,
                        "detail": f"existing match in band={band}"}
        elif band in ("core", "high") and routed.get("hit"):
            hit = routed["hit"]
            if not precheck_mod.prompt_existing(hit):
                return {"status": "exists", "ask": ask, "pack": hit,
                        "detail": f"existing suggested: {hit['title']} ({hit.get('url','')})"}
        elif band == "middle" and routed.get("candidates"):
            author_anyway, chosen = precheck_mod.prompt_middle(routed["candidates"])
            if not author_anyway:
                pack = chosen or {"title": "(the user's pick)", "url": ""}
                return {"status": "exists", "ask": ask, "pack": pack,
                        "detail": f"using existing pack: {pack.get('title')}"}

    # ---- Stage 0: elaborate ----
    log("[0] elaborating spec ...")
    spec, _u = spec_mod.elaborate(ask, model=model, client=client)

    # ---- Stage 0b: clarify ONE genuinely user-visible convention BEFORE confirm ----
    # If the ask left a consequential look-changing convention open (e.g. a halftone's
    # dark-dots vs bright-dots), ask the human now so the confirm examples + the build
    # reflect THEIR choice, not a silent guess. Skipped in non-interactive auto runs
    # (which take the standard-convention default), preserving the acceptance contract.
    if getattr(spec, "clarify", None) and (ambiguity_cb is not None or interactive):
        q = spec.clarify
        opts = list(q.get("options", []))
        spec.clarify = None
        if ambiguity_cb is not None:
            choice = ambiguity_cb({"question": q["question"], "options": opts, "axis": "convention"})
        else:
            choice = confirm_mod.ask_choice(q["question"], opts)
        if choice and choice in opts and choice != q.get("default"):
            log(f"[0b] re-elaborating for your choice: {choice}")
            spec, _u = spec_mod.elaborate(ask + f"\n\nIMPORTANT user choice (honor exactly): {choice}",
                                          model=model, client=client)
            spec.clarify = None   # resolved; do not re-ask

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
        # ADVISORY posture (2026-06-02): the only hard gates are "code runs" + "human
        # approves". Every automated signal below either raises confidence or degrades
        # to a surfaced caveat; none of them dead-ends the run.
        ref0, failing = _best_ref0(spec, model, client, tries=4, log=log)
        caveats = []
        limited = False
        ref0_load_failed = any("load error" in str(f).lower() for f in failing)
        if failing and not ref0_load_failed:
            # The reference could not reproduce every confirmed example. Usually the
            # examples are over-idealized (a solid-input edge case), not the ask being
            # impossible -- carry it as a caveat and run LIMITED; the human gate decides.
            log(f"    reference could not satisfy all examples ({failing}); continuing LIMITED")
            caveats.append("the reference could not reproduce these confirmed examples "
                           f"exactly: {', '.join(str(f) for f in failing)}")
            limited = True
        mutants = mutate.build_operator_mutants(spec, ref0.source, ref0.class_name)
        try:
            mutants += mutate.build_llm_mutants(spec, n=1, model=model, client=client)
        except Exception as e:
            log(f"    (LLM mutant skipped: {e})")
        vet = synth.vet_battery(spec, ref0, mutants, model=model, client=client, log=log)
        kept = vet["kept_checks"]
        if not kept:
            fb = synth.fallback_checks(spec)
            if fb:
                kept = fb
                caveats.append("a full mutation test could not be built; the checks shown "
                               "are your confirmed examples + the output contract only")
            else:
                kept = []
                caveats.append("no automated checks could be built for this op; it is "
                               "verified by your review of the code + before/after only")
            limited = True
            log("    no teeth-passing checks -> LIMITED verification; the human gate is the oracle")
        if vet["unkilled_mutants"]:
            caveats.append(f"{len(vet['unkilled_mutants'])} mutation class(es) were not caught by any test")
            log(f"    residual: {len(vet['unkilled_mutants'])} mutation class(es) uncaught -> surfaced at the gate")

        # ---- Stage 3: N implementations ----
        log(f"[3] generating {n} implementations ...")
        impls, _us = codegen.generate_impls(spec, n=n, model=model, client=client)

        # ---- Stage 4: run battery + differential -- ADVISORY signals, never a gate ----
        log("[4] running battery vs implementations + differential ...")
        run_battery = kept if kept else [_NOOP_CHECK]   # noop -> still get load/run info
        report = _run_vetted(spec, run_battery, impls)
        impl_ids = [c.id for c in impls]
        by_id = {c.id: c for c in impls}
        outcome = differential.analyze_stance(report, impl_ids, spec, candidates_by_id=by_id)
        log(f"    outcome: {outcome['outcome']} -- {outcome['detail']}")

        # Interactive ambiguity resolution is still worth doing when we can -- it is
        # human-in-the-loop, not a dead-end. With a real teeth battery and rounds left,
        # ask + retry on a genuine ambiguity, or retry on a fixable RETRY. Past that
        # (or in LIMITED mode) we NEVER hard-error: we degrade to the best runnable
        # candidate + the human gate.
        if not limited and rounds < max_spec_rounds:
            if outcome["outcome"] == differential.AMBIGUITY:
                log("    [AMBIGUITY] " + outcome["question"])
                _resolve_ambiguity(spec, outcome, confirm_cb, log, ambiguity_cb=ambiguity_cb)
                spec.confirmed = False
                continue
            if outcome["outcome"] == differential.RETRY:
                log("    retrying with fresh implementations ...")
                continue

        # Winner: the confident differential winner, else the best RUNNABLE candidate
        # (ref0 if it runs, else any impl that loaded). Never a dead-end here.
        if outcome["outcome"] == differential.CONFIDENT:
            winner = by_id[outcome["winner_id"]]
        else:
            limited = True
            caveats.append(f"implementations did not reach automated consensus "
                           f"({outcome['outcome']})")
            loaded_impls = [by_id[c] for c in impl_ids if c not in report.load_errors]
            if not ref0_load_failed:
                winner = ref0
            elif loaded_impls:
                winner = loaded_impls[0]
            else:
                winner = ref0   # nothing loaded; the bank load-test fails honestly below
            log(f"    no automated consensus ({outcome['outcome']}); presenting "
                f"'{winner.id}' for human review (LIMITED)")

        _seen = set()
        caveats = [c for c in caveats if not (c in _seen or _seen.add(c))]
        log(f"[5] approval gate (winner: {winner.id}{', LIMITED' if limited else ''})")
        try:
            if approve_cb is not None:
                approve_cb(spec, winner, kept, vet["unkilled_mutants"],
                           limited_verification=limited, caveats=caveats)
            else:
                gate.approve(spec, winner, kept, vet["unkilled_mutants"],
                             render_dir=os.path.join(staging_root, "diff"),
                             interactive=interactive, limited_verification=limited,
                             caveats=caveats)
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
                "kept_checks": kept, "unkilled_mutants": vet["unkilled_mutants"],
                "limited_verification": limited, "caveats": caveats}


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
