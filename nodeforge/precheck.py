"""
v0.1.1 thin retrieval pre-check (decisions.md "[2026-06-01] NodeForge v0.1 scope").

Before the author loop runs, ask: does an existing pack already do this? Reuses
the eval/ retrieval stage (build_index + retrieve) VERBATIM, at the single
high-confidence band only -- a top-1 rerank score >= tau_high surfaces ONE
suggestion; below that we say nothing and author.

tau_high = 0.95, firmed 2026-06-01 by a 5-row live-README spot-check
(eval/adjudication_sheet.md): row 1 held "no" at 0.92, so the precision cut stays
at 0.95; both in-band rows (0.99, 1.00) re-verified "yes". This is the ONE band
calculated with most confidence; the full three-band router is v0.2.

Hard contract (never violated):
  - never auto-install      (a hit is advisory; the human installs, or not)
  - never auto-suppress authoring (default action on a hit is "author anyway")
The pre-check needs a human to confirm, so it is skipped in non-interactive mode.
Any retrieval/network/index failure degrades to None -> author (never blocks).
"""
import os
import sys

# tau_high firmed 2026-06-01 (see module docstring + eval/adjudication_sheet.md).
TAU_HIGH = 0.95
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


def _pick(scored, tau_high=TAU_HIGH, tau_core=TAU_CORE):
    """Precedence-aware HIGH-band decision (v0.2 core-node path). Returns a flat
    hit dict or None. Factored out so it is unit-testable offline.

    CORE PRECEDENCE: a confident built-in core node answers the ask with no
    install and no authoring, so it beats a third-party pack recommendation
    (fixes the wrapper-misdirect, e.g. SD3 nodes live in core). Only if no core
    node clears tau_core do we fall back to the custom-pack HIGH band."""
    if not scored:
        return None
    # scored is sorted desc, so the first row of each source is its best. Inlined
    # (not retrieve.pick_best) so _pick has no dependency on the eval module --
    # it must stay importable/testable offline without anthropic on the path.
    best_core = next((s for s in scored if s.get("source") == "core"), None)
    best_custom = next((s for s in scored if s.get("source") == "custom"), None)
    if best_core and best_core.get("score", 0.0) >= tau_core:
        e = best_core.get("core") or {}
        return {"kind": "core",
                "title": e.get("display_name", best_core.get("id", "?")),
                "node_name": e.get("name", ""),
                "category": e.get("category", ""),
                "url": "",
                "score": best_core["score"],
                "reason": best_core.get("reason", "")}
    if best_custom and best_custom.get("score", 0.0) >= tau_high:
        pack = best_custom.get("pack") or {}
        return {"kind": "custom",
                "title": pack.get("title", best_custom.get("id", "?")),
                "url": pack.get("reference", ""),
                "score": best_custom["score"],
                "reason": best_custom.get("reason", "")}
    return None


def find_existing(ask, tau_high=TAU_HIGH, tau_core=TAU_CORE,
                  model="claude-sonnet-4-6", client=None, log=print):
    """Return the single best hit (a built-in core node OR an existing pack) iff
    one clears its threshold, else None. Costs one rerank LLM call over the
    merged custom-pack + core-node candidate set (Manager index + core index,
    both cached). Degrades to None on any failure so authoring is never blocked.
    `client` is accepted for signature parity with the author loop; the reused
    eval rerank builds its own client from ANTHROPIC_API_KEY."""
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
        return None
    try:
        packs = load_manager_index()
        cands = recall(ask, packs, k=20)
        core_nodes = load_core_index()
        core_cands = [core_to_candidate(e) for e in recall_core(ask, core_nodes, k=15)]
        all_cands = cands + core_cands
        if not all_cands:
            return None
        scored, _usage = rerank(ask, all_cands, model=model)
    except Exception as e:
        log(f"[precheck] retrieval failed ({type(e).__name__}: {e}); skipping -> author")
        return None
    hit = _pick(scored, tau_high, tau_core)
    if hit and hit["kind"] == "core":
        verdict = f"built-in core node '{hit['node_name']}' {hit['score']:.2f} >= {tau_core} -> surfacing"
    elif hit:
        verdict = f"pack match {hit['score']:.2f} >= {tau_high} -> surfacing"
    else:
        verdict = "no confident match -> author"
    log(f"[precheck] checked {len(cands)} pack(s) + {len(core_cands)} core node(s); {verdict}")
    return hit


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
