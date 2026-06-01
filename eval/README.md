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
- `build_core_index.py` — snapshot the **canonical core-node set** (v0.2 core-node
  path) straight from the ComfyUI source registry (`import nodes` +
  `init_builtin_extra_nodes()`, custom_nodes excluded). Run with the embedded
  python; version-stamped JSON at `index_cache/core_nodes.json` (483 nodes,
  ComfyUI 0.19.5). Regenerate after a ComfyUI update.
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
  motivated the core-node path (below).

## Core-node path (v0.2, 2026-06-01) — BUILT + WIRED

Closes the 0/6 gap: a `core_nodes.json` index (483 nodes, `build_core_index.py`)
is folded into the SAME `recall → rerank` as a tagged source, and a precedence
layer (`retrieve.pick_best` / `precheck._pick`) makes a confident built-in BEAT a
third-party pack rec — so "where are the SD3 nodes" resolves to core, not a
wrapper. Re-run scores (`run_eval.py`, claude-sonnet-4-6, n=29, ~$0.78):

- **Recall:** all 5 backend core targets surface in lexical recall (plural-stem +
  a structural resize-family inference: width/height inputs ⇒ a resizer, which
  rescues ImageScale — named "Upscale Image" — from rank 57). After rerank (with a
  built-in-preference instruction: judge a core node on capability, ignore a
  misleading name, don't rank it below a pack that does the same), **4/5 are firm
  hits at tau_core=0.85**: SD3 `EmptySD3LatentImage` 1.00, `ControlNetApplyAdvanced`
  0.95, `ImageScale`/resize 0.95, `ImageToMask` (batch) 0.85. The 5th,
  `canvas_to_mask → ImageToMask` 0.40, falls through the SAFE way (correctly
  *partial* — needs a paint-canvas widget too). The 6th core ask
  (`loadimage_mask_editor_button`) is a **frontend UI button, no backend node —
  documented out of scope.**
- **Precision (clean):** every custom/authoring ask scoring a core node ≥0.85 was
  a GENUINE built-in — `StringConcatenate` (0.90, the `dynamic_filename_prefix`
  ask literally wants a concatenate node) and `SplitImageToTileList` (0.90, a real
  core tiler) — i.e. **zero true false positives**, plus 2 bonus discoveries on
  asks mislabeled non-core (the unresolved-thread confound again).
- **No pack regression:** custom-pack top scores unchanged (color_match 0.97,
  anime 0.95) — the merge is safe.
- **tau_core = 0.85** (PROVISIONAL, n=29; in-band cases hand-verified). Less
  conservative than tau_high=0.95: a wrong "built-in" hint misdirects but carries
  no third-party install/trust cost, and the user still chooses (default = author).
- **Live-verified** (`nodeforge/tests/verify_core_live.py`): SD3 + ControlNet
  resolve to core, a genuine authoring ask falls through to author.

**Documented soft-limit:** generic image RESIZE is IMPROVED by the built-in-
preference fix (ImageScale 0.90→0.95, batch 0.70→0.85, recall 3/5→4/5) but NOT
guaranteed live — for that ultra-common op a polished custom resize pack can still
out-score core `ImageScale` at rerank on some phrasings (a soft cost: advisory,
never auto-installed, not a wrong answer). Core precedence reliably wins for
DISTINCTIVE core nodes (SD3, ControlNet, mask conversion). Tried twice at the
rerank layer (capability description + built-in-preference prompt); stopped there
per the Newson-grain "don't keep patching" rule.

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
