"""
Meta-validation benchmark for the NodeForge self-verification model.

Runs Stages 2-4 WITHOUT the human: for each case, generate a verification battery
from the confirmed spec alone (Stage 2), then run that battery against every
correct and broken implementation (Stage 4) and score three things:

  TEETH        : fraction of broken implementations that are CAUGHT (battery -> fail).
  SPECIFICITY  : fraction of correct implementations that PASS (no false rejection).
  TRIAGE       : on the ambiguity case, does the battery flag the open question AND
                 still pass both valid (differently-interpolated) implementations?

This is the gate before any agent loop is built. The bar: teeth == 1.0 and
specificity == 1.0 across all trials, plus correct triage on the ambiguity case.

Usage (run with the ComfyUI embedded python, which has torch + anthropic):
  python run_benchmark.py --trials 3 --model claude-sonnet-4-6
  python run_benchmark.py --cases luma_key_mask,luma_split   # subset
"""
import os
import sys
import json
import argparse
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cases import CASES
from generate import generate_battery

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load_battery(code):
    """Exec generated module source; return (CHECKS, OPEN_QUESTIONS) or raise."""
    ns = {"__name__": "generated_battery"}
    exec(compile(code, "<generated_battery>", "exec"), ns)
    checks = ns.get("CHECKS")
    if not isinstance(checks, list) or not checks:
        raise ValueError("module did not define a non-empty CHECKS list")
    open_qs = ns.get("OPEN_QUESTIONS", [])
    if not isinstance(open_qs, list):
        open_qs = [str(open_qs)]
    return checks, open_qs


def run_one_check(check_fn, NodeClass):
    """Run a single generated check against an implementation. A raise == failed."""
    try:
        res = check_fn(NodeClass)
        if isinstance(res, (tuple, list)) and len(res) >= 2:
            name = str(res[0])
            passed = bool(res[1])
            detail = str(res[2]) if len(res) > 2 else ""
        else:
            name, passed, detail = getattr(check_fn, "__name__", "check"), False, f"bad return: {res!r}"
        return name, passed, detail
    except Exception as e:
        return getattr(check_fn, "__name__", "check"), False, f"raised {type(e).__name__}: {e}"


def evaluate(checks, NodeClass):
    """Run all checks against an implementation. Returns (verdict, results)."""
    results = [run_one_check(c, NodeClass) for c in checks]
    verdict = "pass" if all(p for _, p, _ in results) else "fail"
    return verdict, results


def synthesize(spec, model, base_seed, retries):
    """Generate + load a battery, retrying on a non-loading draw.

    A battery that fails to generate (truncation) or fails to load (syntax /
    NameError / no CHECKS) is a detectable, free failure: the real verify loop
    just regenerates. We model that here. Returns (checks, open_qs, code, usages,
    attempts) or raises after exhausting retries."""
    usages, last_err = [], None
    for attempt in range(retries + 1):
        try:
            code, usage = generate_battery(spec, model=model, seed_hint=base_seed * 100 + attempt)
            usages.append(usage)
            checks, open_qs = load_battery(code)
            return checks, open_qs, code, usages, attempt + 1
        except Exception as e:
            last_err = e
            if attempt < retries:
                print(f"    draw {attempt+1} unusable ({type(e).__name__}: {e}); regenerating ...")
    raise RuntimeError(f"no usable battery after {retries+1} draws: {last_err}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3, help="battery generations per case")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--cases", default="", help="comma-separated case ids to run (default all)")
    ap.add_argument("--retries", type=int, default=2,
                    help="regenerations allowed when a draw fails to generate/load (models the self-debug loop)")
    ap.add_argument("--out", default=os.path.join(RESULTS_DIR, "results.json"))
    args = ap.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    wanted = set(s.strip() for s in args.cases.split(",") if s.strip())
    cases = [c for c in CASES if not wanted or c["id"] in wanted]

    totals = {"teeth_caught": 0, "teeth_total": 0, "spec_passed": 0, "spec_total": 0,
              "battery_errors": 0, "regenerations": 0, "false_rejections": [], "slips": [], "triage": []}
    in_tok = out_tok = cache_read = cache_write = 0
    report = []

    for case in cases:
        print(f"\n{'='*70}\nCASE: {case['id']}\n{'='*70}")
        case_rec = {"id": case["id"], "trials": []}
        for t in range(args.trials):
            print(f"\n  trial {t+1}/{args.trials}: generating battery from spec ...")
            try:
                checks, open_qs, code, usages, attempts = synthesize(
                    case["spec"], args.model, t, args.retries)
            except Exception as e:
                print(f"    GENERATION ERROR (all draws failed): {e}")
                totals["battery_errors"] += 1
                case_rec["trials"].append({"trial": t, "error": str(e)})
                continue
            for usage in usages:
                in_tok += usage.input_tokens
                out_tok += usage.output_tokens
                cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
                cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
            totals["regenerations"] += (attempts - 1)

            battery_path = os.path.join(RESULTS_DIR, f"{case['id']}_trial{t}.py")
            with open(battery_path, "w", encoding="utf-8") as f:
                f.write(code)

            print(f"    battery: {len(checks)} checks, {len(open_qs)} open question(s)"
                  + (f" (after {attempts} draws)" if attempts > 1 else ""))
            trial_rec = {"trial": t, "n_checks": len(checks), "open_questions": open_qs,
                         "correct": [], "broken": []}

            # SPECIFICITY: correct implementations must PASS
            for label, cls in case["correct"]:
                verdict, results = evaluate(checks, cls)
                ok = verdict == "pass"
                totals["spec_total"] += 1
                totals["spec_passed"] += int(ok)
                mark = "PASS (correct accepted)" if ok else "FALSE REJECTION"
                print(f"      [correct] {label:34s} -> {verdict.upper():4s}  {mark}")
                if not ok:
                    fails = [(n, d) for n, p, d in results if not p]
                    for n, d in fails:
                        print(f"                  x {n}: {d}")
                    totals["false_rejections"].append({"case": case["id"], "trial": t,
                                                        "impl": label, "fails": fails})
                trial_rec["correct"].append({"label": label, "verdict": verdict, "passed": ok})

            # TEETH: broken implementations must be CAUGHT (fail)
            for label, cls in case["broken"]:
                verdict, results = evaluate(checks, cls)
                caught = verdict == "fail"
                totals["teeth_total"] += 1
                totals["teeth_caught"] += int(caught)
                mark = "CAUGHT" if caught else "SLIPPED THROUGH"
                print(f"      [broken ] {label:34s} -> {verdict.upper():4s}  {mark}")
                if not caught:
                    totals["slips"].append({"case": case["id"], "trial": t, "impl": label})
                trial_rec["broken"].append({"label": label, "verdict": verdict, "caught": caught})

            # TRIAGE: ambiguity cases want a flagged open question
            amb = case.get("ambiguity")
            if amb:
                blob = " ".join(open_qs).lower()
                flagged = bool(open_qs) and any(h in blob for h in amb.get("topic_hint", []))
                corrects_ok = all(r["passed"] for r in trial_rec["correct"])
                triage_ok = (flagged == amb.get("expect_open_questions", True)) and corrects_ok
                print(f"      [triage ] open-question flagged={flagged}, "
                      f"all valid variants passed={corrects_ok} -> {'OK' if triage_ok else 'MISS'}")
                if open_qs:
                    for q in open_qs:
                        print(f"                  ? {q}")
                totals["triage"].append({"case": case["id"], "trial": t, "ok": triage_ok,
                                         "flagged": flagged, "corrects_ok": corrects_ok})

            case_rec["trials"].append(trial_rec)
        report.append(case_rec)

    # -------- summary --------
    teeth = totals["teeth_caught"] / totals["teeth_total"] if totals["teeth_total"] else 0.0
    spec = totals["spec_passed"] / totals["spec_total"] if totals["spec_total"] else 0.0
    triage_ok = all(x["ok"] for x in totals["triage"]) if totals["triage"] else None

    print(f"\n{'#'*70}\nMETA-VALIDATION SUMMARY  (model={args.model}, trials/case={args.trials})\n{'#'*70}")
    print(f"  TEETH       : {totals['teeth_caught']}/{totals['teeth_total']} broken caught = {teeth:.0%}")
    print(f"  SPECIFICITY : {totals['spec_passed']}/{totals['spec_total']} correct accepted = {spec:.0%}")
    if triage_ok is not None:
        n_ok = sum(1 for x in totals['triage'] if x['ok'])
        print(f"  TRIAGE      : {n_ok}/{len(totals['triage'])} ambiguity trials handled correctly")
    print(f"  battery errors (no usable battery after retries): {totals['battery_errors']}")
    print(f"  regenerations (draws auto-retried after a non-loading draw): {totals['regenerations']}")
    if totals["slips"]:
        print(f"  !! {len(totals['slips'])} SLIP(S): broken nodes that passed -> {totals['slips']}")
    if totals["false_rejections"]:
        print(f"  !! {len(totals['false_rejections'])} FALSE REJECTION(S): correct nodes failed")
    cost = (in_tok * 3 + out_tok * 15) / 1e6  # rough Sonnet $/Mtok
    print(f"  tokens: in={in_tok} out={out_tok} cache_read={cache_read} cache_write={cache_write} "
          f"(~${cost:.3f})")

    gate = teeth == 1.0 and spec == 1.0 and totals["battery_errors"] == 0 and (triage_ok in (None, True))
    print(f"\n  GATE: {'PASS -- the self-verification model has teeth, build the agent loop' if gate else 'NOT MET -- see slips/false-rejections above'}")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"model": args.model, "trials": args.trials, "teeth": teeth,
                   "specificity": spec, "triage_ok": triage_ok, "totals": totals,
                   "report": report}, f, indent=2, default=str)
    print(f"  full results -> {args.out}")
    sys.exit(0 if gate else 1)


if __name__ == "__main__":
    main()
