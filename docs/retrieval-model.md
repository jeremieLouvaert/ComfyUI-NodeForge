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
- **Schemas CONFIRMED live (2026-05-30):**
  - Manager `custom-node-list.json`: root key `custom_nodes` (array); per entry
    `id, author, title, reference (repo URL), description, files, install_type`
    (+ optional `nodename_pattern`, `pip`, `apt_dependency`, `js_path`).
  - Registry `GET https://api.comfy.org/nodes?page=&limit=&search=`: paginated
    (`page`, `limit`, `total` ~= 4455 packs, `totalPages`); per pack `id, name,
    description, author, repository, downloads, github_stars, rating, status`
    (`NodeStatusActive`...), `publisher{id,name,status}`, `latest_version{version,
    deprecated}`, `tags`, `search_ranking`.
  - **Health signals come free from the registry** (no separate GitHub call needed
    for first-pass health): `github_stars`, `downloads`, `latest_version.deprecated`,
    `status`, `publisher.status`. This directly powers sub-question (iii).
  - **Still to verify at build:** whether `search=` actually filters server-side
    (a quick probe returned the same head as no-search, so treat registry search as
    unconfirmed and lean on our own recall+rerank), and whether a dedicated
    machine-readable *banned/security* list exists beyond the `status`/`deprecated`
    flags.

## 3. Match, rank, route

### Match / rank (a proven LLM-scoring rerank pattern)
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

## 5. Core-node path (v0.2, BUILT 2026-06-01)

The v0.1 custom index has no core nodes, so asks answered by a ComfyUI built-in
misdirected to a custom wrapper pack (row-15 SD3) or to authoring a redundant
node (0/6 in the eval). Closed in v0.2:
- **Index:** `eval/build_core_index.py` snapshots the canonical core set from the
  ComfyUI source registry (`import nodes` + `init_builtin_extra_nodes()`,
  custom_nodes excluded) to `eval/index_cache/core_nodes.json` (483 nodes,
  version-stamped). Authoritative + regenerable; NOT live `/object_info` (which
  can't separate core from a user's installed custom packs).
- **Match:** core entries fold into the SAME `recall → rerank` as a tagged source
  (one LLM call). Core metadata is terse, so recall is plural-stemmed and adds
  structurally-inferred capability words (width/height inputs ⇒ resizer); the
  rerank-facing description gets the same capability sentence so a misleadingly-
  named node (ImageScale = "Upscale Image") is judged on capability. The rerank
  prompt carries a built-in-preference instruction (judge a core node on
  capability, ignore a terse/odd name, don't rank it below a pack that does the
  same) — precision-guarded (a non-matching core node still scores low; eval
  confirmed no inflation / no new false positives / no pack regression).
- **Route (precedence):** a core node clearing `tau_core` (0.85, precision-biased)
  BEATS a custom-pack rec — a built-in needs no install. Wired into the live
  `precheck.py`. Proven: eval (4/5 firm backend hits, 0 true false positives, no
  pack regression) + `verify_core_live.py`.
- **Limits (honest):** frontend-only UI features (e.g. a mask-editor button) have
  no backend node and are out of scope; for ultra-common ops (generic resize) a
  polished custom pack may still out-rank core ImageScale at rerank on some
  phrasings (improved by the built-in-preference fix but not guaranteed live — a
  soft cost). tau_core is provisional on n=29.

## 6. Full three-band router (v0.2, BUILT 2026-06-01)

The thin HIGH-band pre-check was promoted to the full HIGH/MIDDLE/LOW router
(`precheck._route` / `find_existing`), composing with the core-node precedence above:
- **HIGH** (≥ tau_high=0.95) → recommend the one strong match.
- **MIDDLE** (tau_low=0.50 ≤ score < tau_high) → show 1–3 related **custom** packs
  AND offer to author; the human picks via a numbered menu (`prompt_middle`). Health
  (stars/downloads/deprecated) is surfaced best-effort via `build_index.registry_health`
  and a positively-deprecated/archived candidate is hard-excluded; a sub-tau_core core
  node is dropped (a low-confidence "maybe built-in" is uninstallable noise).
- **LOW** (< tau_low) → author silently. Core ≥ tau_core still wins over any band.
- The **24h freshness cache** was already in `build_index.load_manager_index` (TTL +
  stale-fallback-with-age-warning).
- **Gate:** validated by a three-band re-read of the n=29 adjudication
  (`eval/adjudication_sheet.md`) — all 13 "partial" verdicts land in MIDDLE and 0 "yes"
  falls below tau_low, so MIDDLE (which defers to the human, making no binary claim) is
  the structural answer to the known eval confound and needs no HIGH-grade firming.
  tau_low=0.50 kept wide-by-design. Offline `test_precheck.py` + live
  `verify_core_live.py` pass.

## 7. Deferred to later
- Node-level (not pack-level) match granularity for CUSTOM packs.
- Anything requiring richer registry node metadata than v0.1 verifies exists.
