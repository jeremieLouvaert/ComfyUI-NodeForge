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

_EVAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval")


def _pick(scored, tau_high):
    """Pure HIGH-band decision: return the top candidate as a flat dict iff it
    clears tau_high, else None. Factored out so it is unit-testable offline."""
    if not scored:
        return None
    top = scored[0]
    if top.get("score", 0.0) < tau_high:
        return None
    pack = top.get("pack") or {}
    return {"title": pack.get("title", top.get("id", "?")),
            "url": pack.get("reference", ""),
            "score": top["score"],
            "reason": top.get("reason", "")}


def find_existing(ask, tau_high=TAU_HIGH, model="claude-sonnet-4-6", client=None, log=print):
    """Return the single top pack {title, url, score, reason} iff one clears
    tau_high, else None. Costs one rerank LLM call (one Manager index fetch,
    cached 24h). Degrades to None on any failure so authoring is never blocked.
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
        from retrieve import recall, rerank
    except Exception as e:
        log(f"[precheck] retrieval modules unavailable ({type(e).__name__}: {e}); skipping -> author")
        return None
    try:
        packs = load_manager_index()
        cands = recall(ask, packs, k=20)
        if not cands:
            return None
        scored, _usage = rerank(ask, cands, model=model)
    except Exception as e:
        log(f"[precheck] retrieval failed ({type(e).__name__}: {e}); skipping -> author")
        return None
    hit = _pick(scored, tau_high)
    log(f"[precheck] checked {len(cands)} candidate pack(s); "
        + (f"top match {hit['score']:.2f} >= {tau_high} -> surfacing"
           if hit else f"no match >= {tau_high} -> author"))
    return hit


def prompt_existing(hit, _input=input):
    """Show the suggested existing pack and ask. Returns True = author anyway
    (also the default on empty input -- we never auto-suppress authoring),
    False = stop, the user will install the existing pack instead."""
    print("\n[precheck] This may already exist:")
    print(f"    {hit['title']}   (match {hit['score']:.2f})")
    if hit.get("url"):
        print(f"    {hit['url']}")
    if hit.get("reason"):
        print(f"    why: {hit['reason']}")
    print("    NodeForge never installs anything for you -- this is just a heads-up.")
    ans = _input("    [a] author a new node anyway (default)  /  [s] stop, I'll install that: ").strip().lower()
    return not ans.startswith("s")
