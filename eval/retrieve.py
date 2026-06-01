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

Built-in core nodes: some candidates are BUILT-IN ComfyUI core nodes (their description begins \
"Built-in ComfyUI core node"). Judge a core node ONLY on whether it performs the asked operation, \
IGNORING a terse or counterintuitive display name -- e.g. a core node named "Upscale Image" that \
takes width+height inputs performs arbitrary resize/downscale, so for a resize ask it is a full \
match. This is NOT a license to inflate: a core node that does not do the asked thing still scores \
low. But when a core node genuinely performs the asked operation, score it on that merit and do \
NOT rate it below a third-party pack that does the same thing -- the user already has the built-in.

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
        cand = by_key.get(key)
        if cand is None:
            # model may have lightly renamed the id; fuzzy-match on title
            for k2, p2 in by_key.items():
                if key and (key in k2 or k2 in key):
                    cand = p2
                    break
        # source tag drives core-vs-custom precedence downstream. Custom pack
        # candidates (from recall()) are raw Manager dicts with no "source" key
        # -> default "custom"; core candidates (core_to_candidate) carry "core".
        source = (cand or {}).get("source", "custom")
        out.append({"id": key, "score": float(r.get("score", 0.0)),
                    "reason": r.get("reason", ""),
                    "source": source,
                    "pack": cand if source == "custom" else None,
                    "core": (cand or {}).get("_core") if source == "core" else None})
    out.sort(key=lambda d: d["score"], reverse=True)
    return out, resp.usage


# --- v0.2 core-node path (decisions.md "[2026-06-01] NodeForge core-node path") ---
# Core nodes ship with ComfyUI, so a confident core match should answer "you
# already have this" and take PRECEDENCE over recommending a third-party pack
# (the row-15 SD3 wrapper-misdirect). Core entries come from build_core_index.py
# and are folded into the SAME recall->rerank as a tagged source (one LLM call);
# the rerank prompt is unchanged -- the synthesized description below carries the
# "built-in core node" signal, and precedence lives in pick_best()/_pick, not the
# prompt (keeps the proven pack-scoring path untouched).

# Structural capability inference: terse/misleadingly-named core nodes don't
# carry synonym words. A node that takes width+height (or a scale/megapixel
# input) IS a resizer regardless of its display name (e.g. ImageScale displays
# as "Upscale Image" but does arbitrary resize). This adds the resize-family
# vocabulary structurally (from the input signature), NOT via a hand-list of
# node names -- it generalizes to any resizer, core or custom. Precision is still
# gated by the LLM rerank + tau_core; this only widens RECALL.
_RESIZE_INPUTS = {"scale_by", "megapixels", "largest_size", "resolution", "resolution_steps"}
_RESIZE_TOKENS = ["resize", "rescale", "scale", "downscale", "downsize", "size", "dimension", "resolution"]


def _capability_tokens(e):
    names = set(e.get("input_names", []))
    out = []
    if {"width", "height"} <= names or (names & _RESIZE_INPUTS):
        out += _RESIZE_TOKENS
    return out


def _core_haystack(e):
    """Recall signal for a core node. Core DESCRIPTION is usually empty, so lean
    on display_name + category + input/output names + socket types (D2), plus
    structurally-inferred capability words (e.g. resize family for width/height
    nodes)."""
    parts = [e.get("display_name", ""), e.get("name", ""),
             (e.get("category", "") or "").replace("/", " "),
             " ".join(e.get("input_names", [])), " ".join(e.get("input_types", [])),
             " ".join(e.get("output_types", [])), " ".join(e.get("output_names", [])),
             e.get("description", ""), " ".join(_capability_tokens(e))]
    return _tokens(" ".join(parts))


def _stem_set(tokens):
    """Add a naive singular form (masks->mask, boxes->box) so plural asks match
    terse singular core metadata. Scoped to recall_core ONLY -- the shared
    _tokens (and the proven pack path) is untouched."""
    out = set()
    for t in tokens:
        out.add(t)
        if len(t) > 4 and t.endswith("es"):
            out.add(t[:-2])
        elif len(t) > 3 and t.endswith("s"):
            out.add(t[:-1])
    return out


def recall_core(ask, core_nodes, k=25):
    """Cheap lexical recall over the core-node index. Returns up to k core entry
    dicts. No API. Plural-stemmed (masks~mask) and output-type/display-name hits
    are weighted (a 'MASK' output is a strong signal for a 'make a mask' ask).
    k is generous: core metadata is terse so recall is brittle -- surface wide
    and let the LLM rerank + tau_core supply the precision."""
    q = _stem_set(_tokens(ask))
    if not q:
        return []
    scored = []
    for e in core_nodes:
        hay = _stem_set(_core_haystack(e))
        if not hay:
            continue
        overlap = len(q & hay)
        if overlap == 0:
            continue
        strong = _stem_set(set(_tokens(e.get("display_name", "")))
                           | set(t.lower() for t in e.get("output_types", []))
                           | set(t.lower() for t in e.get("output_names", [])))
        strong_hits = len(q & strong)
        scored.append((overlap + strong_hits, e))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [e for _, e in scored[:k]]


def _capability_phrase(e):
    """A natural-language capability sentence from the structural signature, so
    the RERANK (not just recall) can judge a terse/misleadingly-named core node.
    E.g. ImageScale displays as 'Upscale Image' but width+height => it resizes;
    without this the reranker under-scores it and a clearly-described third-party
    resize pack wrongly wins (the exact misdirect this path fixes)."""
    if _capability_tokens(e):  # currently fires for resizers (width/height/scale inputs)
        return " It resizes, rescales, downscales or upscales images to a target size/resolution."
    return ""


def core_to_candidate(e):
    """Shape a core-node entry as a rerank candidate (parallel to a pack dict).
    The description is synthesized from the structured fields so the reranker can
    judge capability without a real prose description."""
    desc = (f"Built-in ComfyUI core node (category {e.get('category','')}). "
            f"Inputs: {', '.join(e.get('input_names', [])) or 'n/a'}. "
            f"Outputs: {', '.join(e.get('output_types', [])) or 'n/a'}.")
    if e.get("description"):
        desc += " " + e["description"]
    desc += _capability_phrase(e)
    return {"id": f"core:{e.get('name','')}", "title": e.get("display_name", e.get("name", "")),
            "description": desc, "source": "core", "_core": e}


def pick_best(scored):
    """From a rerank result, return (best_core_row, best_custom_row) -- the
    highest-scored row of each source (scored is sorted desc, so the first of
    each source is its best). Either may be None."""
    best_core = next((s for s in scored if s.get("source") == "core"), None)
    best_custom = next((s for s in scored if s.get("source") == "custom"), None)
    return best_core, best_custom


def route(scored, tau_high, tau_low):
    """Three-band router. Returns (band, top_score). Install is always
    human-confirmed downstream; this only decides whether AUTHOR is offered."""
    top = scored[0]["score"] if scored else 0.0
    if top >= tau_high:
        return "HIGH", top      # recommend install
    if top < tau_low:
        return "LOW", top       # -> author
    return "MIDDLE", top        # show candidates AND offer author
