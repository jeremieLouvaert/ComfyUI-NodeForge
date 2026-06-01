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
from build_core_index import load_core_index
from retrieve import recall, rerank, route, recall_core, core_to_candidate, pick_best

RESULTS_DIR = os.path.join(HERE, "results")
# v0.2 core-node path: the merged custom+core candidate set changes the rerank
# input, so use a fresh cache (the pack-only v0.1 cache stays as the v0.1 record).
CACHE = os.path.join(RESULTS_DIR, "rerank_core_cache.json")

# Ground-truth core targets for the 6 core-bucket asks (acceptable core node
# names). Empty list = no backend core node exists (frontend-only, out of scope).
CORE_TARGETS = {
    "canvas_to_mask": ["ImageToMask"],
    "downscale_after_upscale": ["ImageScale", "ImageScaleBy", "ImageScaleToTotalPixels"],
    "batch_images_to_masks": ["ImageToMask"],
    "loadimage_mask_editor_button": [],   # frontend UI button -- no backend node (documented limit)
    "missing_sd3_nodes": ["TripleCLIPLoader", "ModelSamplingSD3", "EmptySD3LatentImage"],
    "controlnet_advanced_missing": ["ControlNetApplyAdvanced", "ControlNetApply"],
}


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


def score_ask(ask_rec, packs, core_nodes, model, cache):
    """Recall+rerank one ask over the MERGED custom-pack + core-node candidate
    set (cached). Returns the scored candidate list + the correct-pack rank."""
    aid = ask_rec["id"]
    if aid in cache:
        scored = cache[aid]["scored"]
    else:
        cands = recall(ask_rec["ask"], packs, k=20)
        core_cands = [core_to_candidate(e) for e in recall_core(ask_rec["ask"], core_nodes, k=15)]
        result = rerank(ask_rec["ask"], cands + core_cands, model=model)
        scored_full, usage = (result if isinstance(result, tuple) else (result, None))
        # store a slim, serializable view (carries source + core identity)
        scored = [{"id": s["id"], "score": s["score"], "reason": s["reason"],
                   "source": s.get("source", "custom"),
                   "pack": {"id": (s["pack"] or {}).get("id", ""),
                            "title": (s["pack"] or {}).get("title", ""),
                            "reference": (s["pack"] or {}).get("reference", "")} if s.get("pack") else None,
                   "core": {"name": (s["core"] or {}).get("name", ""),
                            "display_name": (s["core"] or {}).get("display_name", "")} if s.get("core") else None}
                  for s in scored_full]
        cache[aid] = {"scored": scored,
                      "usage": {"in": usage.input_tokens, "out": usage.output_tokens,
                                "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0}
                                if usage else None}
    # correct-pack rank (1-based) among CUSTOM candidates, else None
    correct_rank = None
    rank = 0
    for s in scored:
        if s.get("source") == "core":
            continue
        rank += 1
        if _pack_matches(ask_rec.get("existing_pack", ""), s.get("pack")):
            correct_rank = rank
            break
    return scored, correct_rank


def _best_core(scored):
    """Highest-scored core row as (name, display_name, score), or (None,None,0)."""
    bc, _ = pick_best(scored)
    if not bc:
        return None, None, 0.0
    c = bc.get("core") or {}
    return c.get("name", ""), c.get("display_name", ""), bc.get("score", 0.0)


def evaluate(asks, packs, core_nodes, model, use_llm):
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    if not use_llm and not cache:
        print("!! --no-llm but no cache present; nothing to score."); sys.exit(2)
    rows = []
    for a in asks:
        if a["label"] == "other":
            continue
        if not use_llm and a["id"] not in cache:
            continue
        scored, correct_rank = score_ask(a, packs, core_nodes, model, cache)
        bc, bcustom = pick_best(scored)
        core_name, core_disp, core_score = _best_core(scored)
        # top_score / top_pack measure the CUSTOM-pack routing exactly as in v0.1
        # (the install-rec signal), unaffected by core candidates in the list.
        rows.append({"id": a["id"], "label": a["label"], "bucket": a["pack_in_index"],
                     "top_score": bcustom["score"] if bcustom else 0.0,
                     "top_pack": (bcustom["pack"] or {}).get("title", "") if bcustom and bcustom.get("pack") else "",
                     "correct_rank": correct_rank,
                     "core_name": core_name, "core_disp": core_disp, "core_score": core_score,
                     "n_cand": len(scored)})
    os.makedirs(RESULTS_DIR, exist_ok=True)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), indent=2)
    return rows, cache


def core_metrics(rows, tau_core):
    """At a given tau_core: core RECALL (correct built-in surfaced for the 6 core
    asks) + false "built-in" rate (a core node clears tau_core on a custom/
    authoring ask). Returns a dict; the FP list is for human eyeball (some may be
    genuine bonus core discoveries, not errors)."""
    core_rows = [r for r in rows if r["bucket"] == "core"]
    hit = 0
    detail = []
    for r in core_rows:
        targets = CORE_TARGETS.get(r["id"], [])
        ok = bool(targets) and r["core_name"] in targets and r["core_score"] >= tau_core
        hit += int(ok)
        detail.append((r["id"], r["core_name"], round(r["core_score"], 2), ok, bool(targets)))
    scorable = [r for r in core_rows if CORE_TARGETS.get(r["id"])]  # exclude frontend-only
    fp = [(r["id"], r["label"], r["core_name"], round(r["core_score"], 2))
          for r in rows if r["bucket"] != "core" and r["core_score"] >= tau_core]
    return {"tau_core": tau_core,
            "core_recall": f"{hit}/{len(scorable)}",
            "core_recall_n": hit, "core_scorable": len(scorable),
            "false_builtin": len(fp), "fp_list": fp, "detail": detail}


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
    core_nodes = load_core_index()
    if not core_nodes:
        print("!! core index empty -- run build_core_index.py first (embedded python)."); sys.exit(2)

    rows, cache = evaluate(asks, packs, core_nodes, args.model, use_llm=not args.no_llm)

    print(f"\n{'='*78}\nPER-ASK (n={len(rows)} scored; 'other' excluded)\n{'='*78}")
    print(f"{'id':32s} {'label':10s} {'bkt':7s} {'pack':>5s} {'rank':>4s} {'core':>5s}  best_core / top_pack")
    for r in sorted(rows, key=lambda x: (x["label"], x["bucket"])):
        rk = str(r["correct_rank"]) if r["correct_rank"] else "-"
        tag = (r["core_name"][:24] if r["core_score"] >= 0.5 else r["top_pack"][:24])
        print(f"{r['id']:32s} {r['label']:10s} {r['bucket']:7s} {r['top_score']:5.2f} {rk:>4s} "
              f"{r['core_score']:5.2f}  {tag}")

    # ---- v0.2 core-node path: recall + false-"built-in", swept over tau_core ----
    print(f"\n{'='*78}\nCORE-NODE PATH  (recall on 6 core asks; false 'built-in' on custom+authoring)\n{'='*78}")
    print(f"{'tau_core':>8s} {'core_recall':>11s} {'false_builtin':>14s}")
    core_grid = [core_metrics(rows, tc) for tc in (0.80, 0.85, 0.90, 0.95)]
    for cg in core_grid:
        print(f"{cg['tau_core']:8.2f} {cg['core_recall']:>11s} {cg['false_builtin']:>14d}")
    cm90 = next(cg for cg in core_grid if cg["tau_core"] == 0.90)
    print("\nper core ask @ tau_core=0.90  (ok? / has-backend-target?):")
    for aid, cname, cscore, ok, has in cm90["detail"]:
        print(f"    {aid:32s} -> {cname or '(none)':24s} {cscore:5.2f}  "
              f"{'HIT ' if ok else 'miss'} {'' if has else '[frontend-only, out of scope]'}")
    if cm90["fp_list"]:
        print("\nsuspected false 'built-in' @0.90 (EYEBALL: some may be genuine bonus core discoveries):")
        for aid, lab, cname, cscore in cm90["fp_list"]:
            print(f"    {aid:32s} [{lab}] -> {cname} {cscore:.2f}")
    else:
        print("\nNO false 'built-in' at tau_core=0.90 on any custom/authoring ask.")

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
           "core_path": core_grid, "sweep": grid, "recommended": best}
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
          f"core_recall@.90={cm90['core_recall']} false_builtin@.90={cm90['false_builtin']} "
          f"best_th={best['tau_high']} best_tl={best['tau_low']} "
          f"recall={best['recall_custom']} route_auth={best['authoring_to_author']} "
          f"prec={best['install_precision']:.2f} cost=${(tin*3+tout*15)/1e6:.3f}")


if __name__ == "__main__":
    main()
