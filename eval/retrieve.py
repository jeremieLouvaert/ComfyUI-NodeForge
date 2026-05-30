"""
The retrieval stage under test: cheap lexical recall -> LLM rerank -> 3-band router.

Mirrors the Discover LLM-scoring pattern (comfyui-brain/tools/discover) and the
benchmark/ generate.py Anthropic call style (cached system prompt).

Flow:
  recall(ask, packs)        -> top-K candidate packs by lexical overlap (no API)
  rerank(ask, candidates)   -> per-candidate fit score 0..1 + reason (1 LLM call)
  route(scored, thresholds) -> HIGH (recommend install) | MIDDLE (offer both) |
                               LOW (author); install is always human-confirmed.
"""
import os
import re
import json
import anthropic

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("a an the to of for in on with and or node nodes comfyui image images "
            "that this it from into want need is are be how do does can node's".split())


def _tokens(text):
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 2]


def recall(ask, packs, k=20):
    """Cheap lexical recall: rank packs by token overlap of the ask against
    title + description. Returns up to k candidate pack dicts. No API."""
    q = set(_tokens(ask))
    if not q:
        return []
    scored = []
    for p in packs:
        hay = _tokens(p.get("title", "")) + _tokens(p.get("description", ""))
        if not hay:
            continue
        hayset = set(hay)
        overlap = len(q & hayset)
        if overlap == 0:
            continue
        # light idf-ish weighting: title hits count double
        title_hits = len(q & set(_tokens(p.get("title", ""))))
        scored.append((overlap + title_hits, p))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in scored[:k]]


_RERANK_SYS = """You are the retrieval ranker of a ComfyUI node-finding agent. Given a user's \
plain-language description of the node capability they want, and a list of candidate custom-node \
PACKS (each with a title and description), score how likely each pack actually CONTAINS a node \
that does what the user asked.

Score each candidate 0.0 to 1.0:
- 1.0  the pack clearly provides exactly this capability.
- 0.7-0.9  very likely provides it (description strongly implies the operation).
- 0.4-0.6  plausibly related but you cannot confirm the specific capability.
- 0.1-0.3  same general area, probably not this capability.
- 0.0  unrelated.

Be strict: a pack being in the same domain (e.g. 'image utils') is NOT evidence it has the \
SPECIFIC operation asked for. Reserve >=0.7 for a real match you would stake an install on. \
It is correct and expected to score EVERY candidate low when none of them actually do the asked \
thing -- do not inflate a weak match just because it is the best of a bad list.

Output ONLY a JSON array, one object per candidate you were given, in any order:
[{"id": "<pack id or title>", "score": <float>, "reason": "<one short clause>"}]
No prose, no markdown fences."""


def rerank(ask, candidates, model="claude-sonnet-4-6", max_tokens=1500):
    """One LLM call scoring all candidates for this ask. Returns list of
    {id, score, reason, pack} sorted by score desc. Empty candidates -> []."""
    if not candidates:
        return []
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    listing = []
    by_key = {}
    for i, p in enumerate(candidates):
        key = p.get("id") or p.get("title") or f"cand{i}"
        by_key[key] = p
        listing.append(f'- id: {key}\n  title: {p.get("title","")}\n  description: {p.get("description","")[:300]}')
    user = (f"USER WANTS A NODE THAT: {ask}\n\nCANDIDATE PACKS:\n" + "\n".join(listing) +
            "\n\nScore every candidate now. JSON array only.")
    resp = client.messages.create(
        model=model, max_tokens=max_tokens,
        system=[{"type": "text", "text": _RERANK_SYS, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    txt = "".join(b.text for b in resp.content if b.type == "text").strip()
    m = re.search(r"\[.*\]", txt, re.DOTALL)
    rows = json.loads(m.group(0)) if m else []
    out = []
    for r in rows:
        key = str(r.get("id", ""))
        pack = by_key.get(key)
        if pack is None:
            # model may have lightly renamed the id; fuzzy-match on title
            for k2, p2 in by_key.items():
                if key and (key in k2 or k2 in key):
                    pack = p2
                    break
        out.append({"id": key, "score": float(r.get("score", 0.0)),
                    "reason": r.get("reason", ""), "pack": pack})
    out.sort(key=lambda d: d["score"], reverse=True)
    return out, resp.usage


def route(scored, tau_high, tau_low):
    """Three-band router. Returns (band, top_score). Install is always
    human-confirmed downstream; this only decides whether AUTHOR is offered."""
    top = scored[0]["score"] if scored else 0.0
    if top >= tau_high:
        return "HIGH", top      # recommend install
    if top < tau_low:
        return "LOW", top       # -> author
    return "MIDDLE", top        # show candidates AND offer author
