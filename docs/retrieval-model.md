# NodeForge Retrieval Model (design)

> Status: design, signed off 2026-05-30 (v0.1 AUTHOR + RETRIEVE plan). No retrieval
> harness until the retrieval meta-eval (section 4) passes. Companion to
> docs/self-verification-model.md (the authoring half).

## 0. Why this exists

Probe 2 (demand sizing, 2026-05-30) showed the dominant *confirmed* user pain is
discovery: a node already exists, the user just can't find it. So NodeForge was
reshaped from pure-authoring to AUTHOR + RETRIEVE: "describe what you want -> find
the existing node/pack if one exists, else author + verify + bank a new one."

Honest framing: retrieval is **table-stakes UX**. It overlaps ComfyUI-Copilot
(5.2k stars, does node recommendation) and ComfyUI-Manager search. The authoring +
self-verification loop is the moat and the viral demo. Budget effort accordingly:
retrieval must be solid, not gold-plated.

## 1. The loop position

```
user describes what they want
        |
        v
RETRIEVE  -- index (Manager list + registry, health-filtered)
        |    match/rank candidates against the ask (cheap recall -> LLM rerank)
        v
   route by confidence
   |- HIGH   -> recommend install (show pack + health), human-confirm -> DONE
   |- MIDDLE -> show candidates AND offer to author; human picks
   \- LOW/none -> AUTHOR (docs/self-verification-model.md)
```

RETRIEVE is the new top-level control flow. It never installs on its own and never
silently auto-authors when plausible matches exist.

## 2. Index

- **ComfyUI-Manager `custom-node-list.json`** (pack-level: title, description,
  author, repo URL) and **registry.comfy.org** (pack-level: metadata, publisher,
  version, downloads).
- **v0.1 granularity = pack-level.** The ask is for a *node*; both indexes are
  *pack*-level with prose descriptions, so we match the ask against title +
  description. Node-level granularity (per-node names via `/object_info` of
  installed packs, or richer registry node listings) is a **v0.2 refinement** and a
  stated v0.1 limitation, not hidden.
- **Build-time verification needed (assumed, not yet confirmed):** the exact JSON
  shape of the Manager list, the registry API shape + pagination, and whether a
  machine-readable banned/security list exists.

## 3. Match, rank, route

### Match / rank (reuses the proven Discover LLM-scoring pattern, comfyui-brain/tools/discover)
1. **Cheap recall** (lexical / embedding) -> top-K candidate packs (K ~= 20).
2. **LLM rerank** -> per candidate, a fit score 0..1 + a one-line justification,
   given the user ask + the candidate description + its health signals.

### Route (the retrieve-vs-author crux) -- three bands, never a silent binary
This mirrors self-verification anti-circularity rule (d): ambiguity is a question
for the human, not an auto-resolution.
- **HIGH (score >= tau_high):** present the 1-3 strong matches, recommend install.
  Do not author.
- **LOW (< tau_low) or empty:** route to AUTHOR.
- **MIDDLE:** show candidates AND offer authoring; the human chooses.
- **Install is always human-confirmed**, even at HIGH. Installing third-party code
  is a trust event; the router only decides whether AUTHOR is offered.

### (i) Index freshness
Cache both sources locally as JSON with a `fetched_at` timestamp. Refresh on run if
older than a **24h TTL**. On fetch failure, fall back to the last cache and **warn
loudly with the cache age** -- never use a stale index without surfacing its age
(honest-accounting pattern). Manager list is one GitHub-raw JSON (cheap full
refetch); the registry snapshot is assembled + cached.

### (ii) Match-confidence threshold
Do **not** guess tau. **Calibrate tau_high / tau_low on a labeled eval set** (the
retrieval meta-eval, section 4). Bias: maximize **precision on "recommend install"**
(a confident-wrong install erodes trust fastest) while keeping **recall on "a node
exists"** high enough not to reinvent the wheel. Start conservative (narrow HIGH,
wide MIDDLE so humans adjudicate borderline) and tighten from eval data.

### (iii) Avoiding abandoned / malicious packs
Reuse Discover's repo-health rubric/signals (the tool already exists):
- **Hard-exclude:** archived repos; anything on a known banned/security list (if
  Manager exposes one); packs not resolvable to a real repo.
- **Downrank (not exclude):** low stars + long-stale (mirror Discover anti-pattern:
  `<5 stars AND >12mo stale` heavily penalized).
- **Surface health** (stars, last-commit age, registry-verified publisher,
  downloads) in every recommendation; if health can't be assessed, say so and don't
  recommend.
- **Honest limit (stated to the user, never hidden):** we cannot *prove* a pack is
  safe. Retrieval reduces risk but installing third-party code is a trust event the
  user owns -- the analog of the authoring side's "human-approval gate is the
  security boundary."

## 4. Gate before any harness: the retrieval meta-eval

The authoring half is de-risked (benchmark/ passed). The **retrieval half is new
and unproven.** Per the brain's own "prove the fitness function before the harness"
discipline and the meta-validation precedent that just worked:

Build a **retrieval meta-eval BEFORE the retrieval harness** (the analog of
benchmark/). Reuse **Probe 2's harvested "is there a node for X" asks** (already
labeled retrieval-vs-authoring) as the ground-truth set (existing-pack-name |
genuinely-none). Measure the matcher + router:
- **Recall:** when a node exists, is the right pack recommended?
- **Precision:** are confident-wrong installs avoided?
- **Routing:** is "genuinely none" correctly sent to AUTHOR (ambiguous -> MIDDLE)?
Set tau_high / tau_low from this; only build the live retrieval loop after it clears
a bar.

**Honest caveat:** Probe 2's set is small (n=33, Reddit access-blocked,
retrieval-skewed), so the eval is only as good as its labels -- augment the label
set before trusting tau.

## 5. Deferred to v0.2+
- Node-level (not pack-level) match granularity.
- Anything requiring richer registry node metadata than v0.1 verifies exists.
