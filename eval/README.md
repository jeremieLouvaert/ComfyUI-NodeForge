# NodeForge retrieval meta-eval

The analog of `../benchmark/` for the **retrieval** half (docs/retrieval-model.md
section 4). It runs the retrieval stage (lexical recall → LLM rerank → three-band
router) over a labeled set of real community "is there a node for X" asks and
measures recall / authoring-routing / install-precision, sweeping the router
thresholds.

## Files
- `asks.json` — 37 real asks re-harvested 2026-05-30 from GitHub + forums/HF
  (Reddit blocked again, as in Probe 2). Each labeled by the **thread's own
  resolution**. Buckets: retrieval/custom 10, retrieval/core 6, authoring 13,
  other 8 (other excluded from scoring).
- `build_index.py` — fetch + 24h-TTL-cache the Manager `custom-node-list.json`
  (5048 packs, schema confirmed live) + registry health lookups.
- `retrieve.py` — the stage under test: `recall()` (lexical, no API) → `rerank()`
  (one LLM call, 0..1 fit score) → `route()` (HIGH/MIDDLE/LOW; install always
  human-confirmed).
- `run_eval.py` — scores + sweeps thresholds; caches rerank so re-sweeps are free.

Run with the embedded python (needs `ANTHROPIC_API_KEY`):
```
python run_eval.py            # full run (~$0.50)
python run_eval.py --no-llm   # re-sweep from cache, no API
```

## First-run result (2026-05-30, claude-sonnet-4-6) — GATE DID NOT CLEANLY PASS

Raw automated numbers: labeled-pack recall **1/10**, authoring-routing **0/13**,
install-precision **0.12**. **These numbers are NOT a trustworthy pass/fail
signal** — the run surfaced that the *metric* is confounded, which is exactly what
a gate is for. Two confounds, both real findings:

1. **Exact-match-to-one-labeled-pack severely undercounts recall.** ComfyUI packs
   are **non-unique** — many different packs do the same operation. The reranker
   repeatedly returned a *valid* pack that was not the one the original thread
   happened to name, so exact match scored it wrong. Inspecting top-1 by hand:
   `split_image_grid → ComfyUI-AutoSplitGridImage` (correct), `color_match →
   Wavelet Color Fix` (valid), `anime_remove_background → Anime Character
   Segmentation` (correct, rank 1), `load_folder_sequential → Sequential Image
   Loader` (correct), `read_prompt_from_file → iTools` (valid). ~5-6/10 plausibly
   correct top-1s, not 1/10.

2. **"authoring" = unresolved-thread ≠ "no pack exists".** The reranker found
   *real* packs for several asks we labeled authoring because their thread went
   unanswered: `claude_node → "ComfyUI and Claude"` (1.00), `outpaint →
   "Infinity-Canvas"` (0.85), `text_to_music → "InspireMusic Plugin"` (0.90).
   Some are genuine discoveries; others over-confident (the music one ignores the
   8GB constraint). So scoring these as false-positive installs is partly wrong
   ground truth. This empirically confirms Probe 2's own caveat that
   unresolved-thread is a weak authoring signal.

Confirmed cleanly (not confounded):
- **Core-node-awareness gap: 0/6.** None of the 6 asks whose true answer is a
  built-in core/frontend node were found in the *custom* index — expected, and it
  motivates a core-node path in v0.2.

## What this gates (honest)
- **Do NOT set the router thresholds from these numbers.** Threshold calibration
  (retrieval sub-question ii) is **blocked on a human top-1 adjudication pass**:
  judge each of the 29 top-1 recommendations yes/partial/no, which yields
  trustworthy precision/recall. Cheap (one glance per item) and it is the same
  "human judgment at the cheapest point" principle the authoring half uses.
- **Product signal to weigh:** the reranker assigns HIGH (≥0.85) to several
  genuinely-hard asks, so a naive threshold router would under-trigger the AUTHOR
  branch (the moat). Calibration must protect AUTHOR-routing, not just
  install-precision.
- **Possible metric fix (v0.2):** replace exact-match with an LLM-judge of
  "does the top pack satisfy the ask?", itself teeth-checked — but a human
  adjudication pass is the trustworthy first step and the gate for v0.1.
