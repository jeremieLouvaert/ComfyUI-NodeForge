"""
Retrieval pre-check: a full three-band router (v0.2; promotes the v0.1.1 thin
HIGH-band pre-check). Before the author loop runs, ask: does an existing built-in
or pack already do this? Reuses the eval/ retrieval stage (build_index + retrieve)
VERBATIM, then routes the top scores into three bands (docs/retrieval-model.md §3):

  - HIGH   (score >= tau_high=0.95)        -> recommend the one strong match (install)
  - MIDDLE (tau_low <= score < tau_high)   -> show 1-3 related packs AND offer author
  - LOW    (score < tau_low=0.50)          -> say nothing, author

Plus the v0.2 core-node precedence: a confident built-in (core >= tau_core=0.85)
answers with NO install and NO author, so it beats any custom band (including a
MIDDLE custom band -- don't offer-to-author what ComfyUI already ships).

Thresholds (eval/adjudication_sheet.md):
  - tau_high=0.95 FIRMED (5-row live-README spot-check; row 1 held "no" at 0.92).
  - tau_low=0.50 KEPT, wide-MIDDLE-by-design: the three-band re-read of the n=29
    adjudication put all 13 "partial" verdicts in MIDDLE and 0 "yes" below 0.50
    (no clean match silently authored). The costly error is a TOO-HIGH tau_low
    silently authoring a duplicate (Probe-2's dominant discovery pain), not a
    too-low one (shows a weak candidate the human ignores). Provisional n=29.
  - tau_core=0.85 (precision-biased; a wrong built-in hint only misdirects).

Hard contract (never violated, every band):
  - never auto-install      (every match is advisory; the human installs, or not)
  - never auto-suppress authoring (default action is always "author anyway")
The pre-check needs a human, so it is skipped in non-interactive mode. Any
retrieval/network/index failure degrades to the LOW band -> author (never blocks).
"""
import os
import sys

# tau_high firmed 2026-06-01 (see module docstring + eval/adjudication_sheet.md).
TAU_HIGH = 0.95
# tau_low: MIDDLE floor. score < tau_low -> author silently; tau_low <= score <
# tau_high -> show candidates + offer author. Kept wide-by-design (see the
# "MIDDLE band -- three-band re-read" section of eval/adjudication_sheet.md).
# Provisional on n=29.
TAU_LOW = 0.50
# tau_core: confidence to claim "ComfyUI already ships this" (v0.2 core-node path).
# Set 0.85 from the core-node eval (eval/README.md "core-node path", 2026-06-01,
# n=29, after the rerank built-in-preference fix): every custom/authoring ask
# scoring a core node >=0.85 was a GENUINE built-in match (StringConcatenate 0.90,
# SplitImageToTileList 0.90 -- verified real core nodes), i.e. ZERO true false
# positives down to 0.85. Backend hits @>=0.85 = 4/5: SD3 (1.00),
# ControlNetApplyAdvanced (0.95), ImageScale/resize (0.95), ImageToMask batch
# (0.85); the 5th (canvas->ImageToMask 0.40) is correctly partial. Precision-biased
# but less conservative than tau_high (0.95): a wrong "built-in" hint misdirects
# but, unlike a wrong install rec, carries no third-party-code trust/security cost,
# and the user still chooses (default = author). PROVISIONAL n=29; in-band cases
# hand-verified.
TAU_CORE = 0.85

_EVAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval")


def _custom_hit(s):
    """Flatten a custom-pack rerank row to a hit dict (the shape cli/prompt use)."""
    pack = s.get("pack") or {}
    return {"kind": "custom",
            "title": pack.get("title", s.get("id", "?")),
            "url": pack.get("reference", ""),
            "score": s.get("score", 0.0),
            "reason": s.get("reason", "")}


def _core_hit(s):
    """Flatten a core-node rerank row to a hit dict."""
    e = s.get("core") or {}
    return {"kind": "core",
            "title": e.get("display_name", s.get("id", "?")),
            "node_name": e.get("name", ""),
            "category": e.get("category", ""),
            "url": "",
            "score": s.get("score", 0.0),
            "reason": s.get("reason", "")}


def _route(scored, tau_high=TAU_HIGH, tau_low=TAU_LOW, tau_core=TAU_CORE):
    """Full three-band router (v0.2). Returns a band + the single HIGH/core hit
    (if any) + the MIDDLE candidate list. Pure/offline -- unit-testable with no
    network (operates on the already-`scored` rerank rows):

      {"band": "core"|"high"|"middle"|"low",
       "hit":  <hit dict> | None,      # set for core/high
       "candidates": [<hit dict>...]}  # 1-3 custom packs, set for middle

    PRECEDENCE (composes with the shipped core-node path): a confident built-in
    (core >= tau_core) answers with no install AND no author, so it beats any
    custom band -- including a MIDDLE custom band (don't offer-to-author what
    ComfyUI already ships). Only if no core node clears tau_core do we consider
    the custom HIGH band, then the custom MIDDLE band, then LOW -> author.

    MIDDLE candidates are CUSTOM packs only (things you would install). A core
    node either wins confidently (>= tau_core) or is dropped -- a low-confidence
    "maybe it's built-in" is noise and cannot be installed anyway."""
    if not scored:
        return {"band": "low", "hit": None, "candidates": []}
    # scored is sorted desc, so the first row of each source is its best.
    best_core = next((s for s in scored if s.get("source") == "core"), None)
    best_custom = next((s for s in scored if s.get("source") == "custom"), None)
    if best_core and best_core.get("score", 0.0) >= tau_core:
        return {"band": "core", "hit": _core_hit(best_core), "candidates": []}
    if best_custom and best_custom.get("score", 0.0) >= tau_high:
        return {"band": "high", "hit": _custom_hit(best_custom), "candidates": []}
    mids = [s for s in scored if s.get("source") == "custom"
            and tau_low <= s.get("score", 0.0) < tau_high]
    if mids:
        return {"band": "middle", "hit": None,
                "candidates": [_custom_hit(s) for s in mids[:3]]}
    return {"band": "low", "hit": None, "candidates": []}


def _pick(scored, tau_high=TAU_HIGH, tau_core=TAU_CORE):
    """Backward-compatible HIGH/core-band pick: the single best built-in or pack
    iff it clears its threshold, else None. Thin wrapper over _route so the band
    logic lives in one place. Retained for the offline unit tests and HIGH-only
    callers; the full router is _route / find_existing."""
    routed = _route(scored, tau_high, TAU_LOW, tau_core)
    return routed["hit"] if routed["band"] in ("core", "high") else None


def _norm_repo(url):
    """Normalize a repo URL to 'owner/repo' (lowercased, no scheme/.git) so a
    Manager `reference` and a registry `repository` can be matched for health."""
    if not url:
        return ""
    u = url.strip().lower().rstrip("/")
    for pre in ("https://", "http://", "git@", "www."):
        if u.startswith(pre):
            u = u[len(pre):]
    u = u.replace("github.com/", "").replace("github.com:", "")
    if u.endswith(".git"):
        u = u[:-4]
    parts = [p for p in u.split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else u


def _enrich_health(ask, candidates, exclude_deprecated):
    """Best-effort: attach registry health (stars/downloads/deprecated) to each
    candidate by matching repo URL and -- if exclude_deprecated -- drop matched
    deprecated/archived packs (fall through to the next candidate). Bounded HTTP,
    no-op on any failure (returns candidates unchanged), never gates authoring,
    and NEVER excludes on ABSENCE of data (only on a positive deprecated/archived
    flag). No new health rubric -- reuses build_index.registry_health (the hook
    retrieval-model.md §3(iii) calls for)."""
    if not candidates:
        return candidates
    try:
        from build_index import registry_health
        health = registry_health(ask, limit=10)
    except Exception:
        return candidates
    if not health:
        return candidates
    by_repo = {}
    for h in health.values():
        r = _norm_repo(h.get("repository", ""))
        if r:
            by_repo[r] = h
    out = []
    for c in candidates:
        h = by_repo.get(_norm_repo(c.get("url", "")))
        if h:
            archived = str(h.get("status", "")).lower() in (
                "nodestatusbanned", "banned", "archived", "deleted")
            dep = bool(h.get("deprecated")) or archived
            if exclude_deprecated and dep:
                continue  # hard-exclude a known-bad pack from the shown list
            c = dict(c)
            c["health"] = {"stars": h.get("github_stars", 0),
                           "downloads": h.get("downloads", 0),
                           "deprecated": dep}
        out.append(c)
    return out


def find_existing(ask, tau_high=TAU_HIGH, tau_low=TAU_LOW, tau_core=TAU_CORE,
                  model="claude-sonnet-4-6", client=None, log=print):
    """Route the ask into one of the three retrieval bands. Returns:
       {"band": "core"|"high"|"middle"|"low", "hit": <dict|None>,
        "candidates": [<dict>...]}
    Costs one rerank LLM call over the merged custom-pack + core-node candidate
    set (Manager index + core index, both cached, 24h TTL), plus a best-effort
    registry-health lookup only when packs are surfaced. Degrades to the LOW band
    (-> author) on any failure so authoring is never blocked. `client` is
    accepted for signature parity with the author loop; the reused eval rerank
    builds its own client from ANTHROPIC_API_KEY."""
    _LOW = {"band": "low", "hit": None, "candidates": []}
    if _EVAL not in sys.path:
        sys.path.insert(0, _EVAL)
    # The reused eval rerank reads ANTHROPIC_API_KEY from env only; make the
    # pre-check honor nodeforge's env-or-key-file convention so a key-file-only
    # setup doesn't silently skip retrieval while the author loop works.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        try:
            from . import keys
            os.environ["ANTHROPIC_API_KEY"] = keys.anthropic_key()
        except Exception:
            pass
    try:
        from build_index import load_manager_index
        from build_core_index import load_core_index
        from retrieve import recall, rerank, recall_core, core_to_candidate
    except Exception as e:
        log(f"[precheck] retrieval modules unavailable ({type(e).__name__}: {e}); skipping -> author")
        return _LOW
    try:
        packs = load_manager_index()
        cands = recall(ask, packs, k=20)
        core_nodes = load_core_index()
        core_cands = [core_to_candidate(e) for e in recall_core(ask, core_nodes, k=15)]
        all_cands = cands + core_cands
        if not all_cands:
            return _LOW
        scored, _usage = rerank(ask, all_cands, model=model)
    except Exception as e:
        log(f"[precheck] retrieval failed ({type(e).__name__}: {e}); skipping -> author")
        return _LOW
    routed = _route(scored, tau_high, tau_low, tau_core)
    # Health enrichment, best-effort, only where we surface installable packs.
    # MIDDLE hard-excludes a known-deprecated/archived candidate (human is
    # adjudicating -- don't hand them a dead pack); HIGH only attaches health so
    # a deprecated-but-strong match is surfaced WITH a warning rather than hidden.
    if routed["band"] == "middle":
        routed["candidates"] = _enrich_health(ask, routed["candidates"], exclude_deprecated=True)
        if not routed["candidates"]:
            routed = {"band": "low", "hit": None, "candidates": []}
    elif routed["band"] == "high" and routed.get("hit"):
        enriched = _enrich_health(ask, [routed["hit"]], exclude_deprecated=False)
        if enriched:
            routed["hit"] = enriched[0]
    band = routed["band"]
    if band == "core":
        h = routed["hit"]
        verdict = f"built-in core node '{h['node_name']}' {h['score']:.2f} >= {tau_core} -> surfacing"
    elif band == "high":
        h = routed["hit"]
        verdict = f"pack match {h['score']:.2f} >= {tau_high} -> recommend install"
    elif band == "middle":
        verdict = (f"{len(routed['candidates'])} candidate(s) in "
                   f"[{tau_low}, {tau_high}) -> show + offer author")
    else:
        verdict = "no confident match -> author"
    log(f"[precheck] checked {len(cands)} pack(s) + {len(core_cands)} core node(s); {verdict}")
    return routed


def prompt_existing(hit, _input=input):
    """Show the suggested existing node/pack and ask. Returns True = author
    anyway (also the default on empty input -- we never auto-suppress authoring),
    False = stop, the user will use the existing node/pack instead."""
    if hit.get("kind") == "core":
        print("\n[precheck] ComfyUI already ships a node for this:")
        print(f"    {hit['title']}   (core node '{hit['node_name']}', match {hit['score']:.2f})")
        if hit.get("category"):
            print(f"    category: {hit['category']}")
        if hit.get("reason"):
            print(f"    why: {hit['reason']}")
        print("    It is built in -- no install and no new node needed.")
        ans = _input("    [a] author a new node anyway (default)  /  [s] stop, I'll use the built-in: ").strip().lower()
        return not ans.startswith("s")
    print("\n[precheck] This may already exist:")
    print(f"    {hit['title']}   (match {hit['score']:.2f})")
    if hit.get("url"):
        print(f"    {hit['url']}")
    if hit.get("reason"):
        print(f"    why: {hit['reason']}")
    print("    NodeForge never installs anything for you -- this is just a heads-up.")
    ans = _input("    [a] author a new node anyway (default)  /  [s] stop, I'll install that: ").strip().lower()
    return not ans.startswith("s")


def prompt_middle(candidates, _input=input):
    """MIDDLE band: show 1-3 possibly-related packs (none a confident match) AND
    offer to author. Returns (author_anyway: bool, chosen: dict|None):
      - empty / 'a' (default)  -> (True, None)   author a new node (never suppressed)
      - '1'..'N'               -> (False, cand)  stop; the user will install that pack
      - out-of-range number    -> (True, None)   ambiguous -> safe default = author
      - 's' / anything else     -> (False, None)  stop, no author, no pick
    NodeForge never installs anything -- a pick just means "don't author"."""
    print("\n[precheck] No confident match, but these packs look possibly related:")
    for i, c in enumerate(candidates, 1):
        line = f"    [{i}] {c['title']}   (match {c['score']:.2f})"
        h = c.get("health")
        if h:
            bits = []
            if h.get("stars"):
                bits.append(f"★{h['stars']}")
            if h.get("downloads"):
                bits.append(f"⬇{h['downloads']}")
            if h.get("deprecated"):
                bits.append("DEPRECATED")
            if bits:
                line += "   " + " ".join(bits)
        print(line)
        if c.get("url"):
            print(f"        {c['url']}")
        if c.get("reason"):
            print(f"        why: {c['reason']}")
    print("    NodeForge never installs anything for you -- this is just a heads-up.")
    n = len(candidates)
    ans = _input(f"    [a] author a new node (default)  /  [1-{n}] stop, I'll install that one  "
                 f"/  [s] stop: ").strip().lower()
    if ans == "" or ans.startswith("a"):
        return True, None
    if ans.isdigit():
        idx = int(ans)
        if 1 <= idx <= n:
            return False, candidates[idx - 1]
        return True, None  # out-of-range -> never auto-suppress authoring
    return False, None      # 's' or anything else -> stop, no author
