"""
NodeForge RETRIEVAL meta-eval (Deliverable 2 / docs/retrieval-model.md section 4).

The analog of benchmark/ for the retrieval half. Runs the retrieval stage
(recall -> rerank -> route) over the labeled asks in asks.json and measures, by
sweeping the router thresholds:

  RECALL (retrieval-custom): is the correct existing pack the top recommendation?
  ROUTING (authoring):       is a genuinely-novel ask routed to AUTHOR (not HIGH)?
  INSTALL PRECISION:         of everything routed HIGH, what fraction is a CORRECT
                             pack recommendation (the trust metric -- a confident
                             wrong install is the worst outcome).

Buckets handled honestly:
  - retrieval/custom : scored for recall + precision.
  - retrieval/core   : answer is a built-in node NOT in the custom index; reported
                       separately as the "core-node awareness gap", not a failure.
  - authoring        : scored for routing + precision.
  - other            : excluded (not a does-a-node-exist ask).

Per-ask rerank results are CACHED to results/rerank_cache.json so threshold
sweeping costs nothing after the first scoring pass.

Run with the ComfyUI embedded python (has anthropic); needs ANTHROPIC_API_KEY:
  python run_eval.py
  python run_eval.py --no-llm     # re-sweep thresholds from cache only
"""
import os
import sys
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_index import load_manager_index
from retrieve import recall, rerank, route

RESULTS_DIR = os.path.join(HERE, "results")
CACHE = os.path.join(RESULTS_DIR, "rerank_cache.json")


def _distinctive(pack_name):
    """Reduce 'ComfyUI-KJNodes' / 'was-node-suite-comfyui' to comparable tokens."""
    s = pack_name.lower()
    for junk in ("comfyui", "comfy", "-", "_", "/", "nodes", "node", "suite"):
        s = s.replace(junk, " ")
    return [t for t in s.split() if len(t) > 2]


def _pack_matches(labeled, cand_pack):
    """Does a candidate pack correspond to the labeled existing_pack?
    Match on distinctive tokens against the candidate's id/title/reference."""
    if not cand_pack or not labeled:
        return False
    hay = " ".join([str(cand_pack.get("id", "")), str(cand_pack.get("title", "")),
                    str(cand_pack.get("reference", ""))]).lower()
    toks = _distinctive(labeled)
    if not toks:
        return False
    return all(t in hay for t in toks) or any(t in hay for t in toks if len(t) > 4)


def score_ask(ask_rec, packs, model, cache):
    """Recall+rerank one ask (cached). Returns the scored candidate list +
    derived flags (top score, correct-pack rank)."""
    aid = ask_rec["id"]
    if aid in cache:
        scored = cache[aid]["scored"]
    else:
        cands = recall(ask_rec["ask"], packs, k=20)
        result = rerank(ask_rec["ask"], cands, model=model)
        scored_full, usage = (result if isinstance(result, tuple) else (result, None))
        # store a slim, serializable view
        scored = [{"id": s["id"], "score": s["score"], "reason": s["reason"],
                   "pack": {"id": (s["pack"] or {}).get("id", ""),
                            "title": (s["pack"] or {}).get("title", ""),
                            "reference": (s["pack"] or {}).get("reference", "")} if s["pack"] else None}
                  for s in scored_full]
        cache[aid] = {"scored": scored,
                      "usage": {"in": usage.input_tokens, "out": usage.output_tokens,
                                "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0}
                                if usage else None}
    # correct-pack rank (1-based) among scored, else None
    correct_rank = None
    for i, s in enumerate(scored):
        if _pack_matches(ask_rec.get("existing_pack", ""), s.get("pack")):
            correct_rank = i + 1
            break
    return scored, correct_rank


def evaluate(asks, packs, model, use_llm):
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    if not use_llm and not cache:
        print("!! --no-llm but no cache present; nothing to score."); sys.exit(2)
    rows = []
    for a in asks:
        if a["label"] == "other":
            continue
        if not use_llm and a["id"] not in cache:
            continue
        scored, correct_rank = score_ask(a, packs, model, cache)
        rows.append({"id": a["id"], "label": a["label"], "bucket": a["pack_in_index"],
                     "top_score": scored[0]["score"] if scored else 0.0,
                     "top_pack": (scored[0]["pack"] or {}).get("title", "") if scored else "",
                     "correct_rank": correct_rank,
                     "n_cand": len(scored)})
    os.makedirs(RESULTS_DIR, exist_ok=True)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=2)
    return rows, cache


def sweep(rows, tau_highs, tau_lows):
    """For each (tau_high, tau_low) compute the headline metrics."""
    out = []
    cust = [r for r in rows if r["label"] == "retrieval" and r["bucket"] == "custom"]
    auth = [r for r in rows if r["label"] == "authoring"]
    for th in tau_highs:
        for tl in tau_lows:
            if tl > th:
                continue
            high_total = corr_high = 0
            recall_hit = 0
            for r in cust:
                band, top = route_from(r, th, tl)
                # recall: correct pack is the top recommendation at HIGH
                if band == "HIGH" and r["correct_rank"] == 1:
                    recall_hit += 1
                if band == "HIGH":
                    high_total += 1
                    if r["correct_rank"] == 1:
                        corr_high += 1
            auth_to_author = 0
            for r in auth:
                band, _ = route_from(r, th, tl)
                if band == "LOW":
                    auth_to_author += 1
                if band == "HIGH":
                    high_total += 1  # a HIGH on an authoring ask = confident-wrong install
            precision = (corr_high / high_total) if high_total else 1.0
            out.append({
                "tau_high": th, "tau_low": tl,
                "recall_custom": f"{recall_hit}/{len(cust)}",
                "recall_pct": recall_hit / len(cust) if cust else 0.0,
                "authoring_to_author": f"{auth_to_author}/{len(auth)}",
                "routing_pct": auth_to_author / len(auth) if auth else 0.0,
                "install_precision": precision,
                "n_recommended": high_total,
            })
    return out


def route_from(row, th, tl):
    top = row["top_score"]
    if top >= th:
        return "HIGH", top
    if top < tl:
        return "LOW", top
    return "MIDDLE", top


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--no-llm", action="store_true", help="re-sweep from cache only (no API)")
    args = ap.parse_args()

    data = json.load(open(os.path.join(HERE, "asks.json"), encoding="utf-8"))
    asks = data["asks"]
    packs = load_manager_index()

    rows, cache = evaluate(asks, packs, args.model, use_llm=not args.no_llm)

    print(f"\n{'='*78}\nPER-ASK (n={len(rows)} scored; 'other' excluded)\n{'='*78}")
    print(f"{'id':32s} {'label':10s} {'bkt':7s} {'top':>5s} {'rank':>4s}  top_pack")
    for r in sorted(rows, key=lambda x: (x["label"], x["bucket"])):
        rk = str(r["correct_rank"]) if r["correct_rank"] else "-"
        print(f"{r['id']:32s} {r['label']:10s} {r['bucket']:7s} {r['top_score']:5.2f} {rk:>4s}  {r['top_pack'][:30]}")

    # core-bucket finding (reported, not scored as failure)
    core = [r for r in rows if r["bucket"] == "core"]
    core_found = sum(1 for r in core if r["correct_rank"])
    print(f"\n[core-node-awareness gap] {len(core)} asks whose answer is a built-in node "
          f"(not in the custom index); custom-index recall found {core_found}/{len(core)} "
          f"(expected ~0 -> motivates a core-node path in v0.2).")

    grid = sweep(rows, [0.6, 0.7, 0.8, 0.9], [0.3, 0.4, 0.5])
    print(f"\n{'='*78}\nTHRESHOLD SWEEP  (pick max install_precision, then recall)\n{'='*78}")
    print(f"{'tau_hi':>6s} {'tau_lo':>6s} {'recall':>9s} {'route_auth':>11s} {'precision':>9s} {'#rec':>5s}")
    for g in grid:
        print(f"{g['tau_high']:6.1f} {g['tau_low']:6.1f} {g['recall_custom']:>9s} "
              f"{g['authoring_to_author']:>11s} {g['install_precision']:9.2f} {g['n_recommended']:5d}")

    # recommended operating point: highest precision, tie-broken by recall
    best = sorted(grid, key=lambda g: (g["install_precision"], g["recall_pct"]), reverse=True)[0]
    print(f"\nRECOMMENDED tau_high={best['tau_high']}, tau_low={best['tau_low']}: "
          f"recall {best['recall_custom']}, routing {best['authoring_to_author']}, "
          f"install_precision {best['install_precision']:.2f}")

    out = {"model": args.model, "n_scored": len(rows), "rows": rows,
           "core_gap": {"total": len(core), "found": core_found},
           "sweep": grid, "recommended": best}
    json.dump(out, open(os.path.join(RESULTS_DIR, "eval_results.json"), "w", encoding="utf-8"),
              indent=2)
    # token accounting
    tin = sum((cache[k]["usage"]["in"] for k in cache if cache[k].get("usage")), 0)
    tout = sum((cache[k]["usage"]["out"] for k in cache if cache[k].get("usage")), 0)
    print(f"\ntokens: in={tin} out={tout} (~${(tin*3+tout*15)/1e6:.3f} at Sonnet rates)")
    print(f"results -> {os.path.join(RESULTS_DIR, 'eval_results.json')}")

    # Compact ASCII verdict (short line survives the flaky terminal channel).
    cust = [r for r in rows if r["label"] == "retrieval" and r["bucket"] == "custom"]
    auth = [r for r in rows if r["label"] == "authoring"]
    surfaced = sum(1 for r in cust if r["correct_rank"])     # labeled pack anywhere in candidates
    top1 = sum(1 for r in cust if r["correct_rank"] == 1)    # labeled pack ranked #1
    print("VERDICT "
          f"n={len(rows)} cust={len(cust)} labeled_surfaced={surfaced} labeled_top1={top1} "
          f"core_found={core_found}/{len(core)} "
          f"best_th={best['tau_high']} best_tl={best['tau_low']} "
          f"recall={best['recall_custom']} route_auth={best['authoring_to_author']} "
          f"prec={best['install_precision']:.2f} cost=${(tin*3+tout*15)/1e6:.3f}")


if __name__ == "__main__":
    main()
