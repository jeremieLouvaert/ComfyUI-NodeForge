"""
Stage 0 -- spec elaboration.

Turns a vague NL ask into a structured records.Spec via ONE LLM call. The model
returns JSON matching the Spec schema, including 3-6 confirmed-example candidates
whose input fixtures use the synthetic generators NodeForge can build
(fixtures.GENERATORS). The human confirms/edits this in Stage 1 (confirm.py)
before any code is written.
"""
import json
import re

from . import records, keys


_SPEC_SYSTEM = """You are the spec-elaboration stage of a ComfyUI node-authoring agent. \
Given a vague natural-language ask for a custom node, produce a STRUCTURED SPEC that a \
human will confirm before any code is written. You do not write code.

ComfyUI conventions:
- IMAGE tensor: torch.float32, shape [B,H,W,C], values in [0,1], C=3 (RGB).
- MASK tensor: torch.float32, shape [B,H,W], values in [0,1] (NO channel dimension).
- INPUT_TYPES is a dict like {"required": {"image": ["IMAGE"], "amount": ["FLOAT", {"default":1.0,"min":0.0,"max":5.0,"step":0.05}]}}.
  Use a list [type, opts] per widget. Numeric widgets are "INT"/"FLOAT" with default/min/max/step.
- RETURN_TYPES is a list of type strings, e.g. ["IMAGE"] or ["IMAGE","IMAGE"] or ["MASK"].

The confirmed EXAMPLES are the trusted oracle, so make them concrete and checkable on
TINY synthetic inputs a human can reason about. Each example's input is built by one of
these synthetic generators (use ONLY these):
- "solid"          params: {"color":[r,g,b], "h":H, "w":W}        a flat block of one color
- "gradient"       params: {"axis":"x"|"y", "h":H, "w":W}         a 0..1 luminance ramp
- "checkerboard"   params: {"cell":N, "h":H, "w":W, "lo":a, "hi":b}  high-frequency 2-value board
- "seeded_texture" params: {"seed":N, "h":H, "w":W}              deterministic random texture
- "known_pattern"  params: {"name":"rgb_corners", "h":H, "w":W}  primaries in the 4 corners

Each example also has an "args" object: the NON-image widget values that example
assumes (e.g. {"color_highlights":"#0000ff","gamma":1.0}). If an example's described
behavior depends on a specific widget value (a color, a threshold, an amount), PUT
THAT VALUE IN "args" -- otherwise the example will be checked at the widget default
and a correct node will be wrongly rejected. Omit args (or use {}) only when the
example holds at the declared widget defaults. The "image" input is NEVER in args
(it comes from input_spec).

Each example expectation has a "kind":
- "literal":  the output equals a pinned value on this fixture. Put the value in "literal"
  (a number, or a small nested list shaped like one output pixel or the whole output). Use
  for endpoint/anchor cases (e.g. "a pure black input maps to colorA").
- "relation": an input->output relation (e.g. "output red channel equals input blue channel").
- "invariant": a property of the output (range, shape, conservation, identity-at-neutral).
Prefer relations/invariants over literals except for clear anchor points (anti-circularity:
a recomputed expected value is just a second implementation).

Output ONLY a JSON object, no markdown fences, with this exact schema:
{
  "title": "Short Title Case Name",
  "input_types": {"required": {...}, "optional": {...}},
  "return_types": ["IMAGE"],
  "return_names": null,
  "contract": "one or two sentences: shapes, ranges, dtype, any fixed formula (e.g. Rec.709 luma).",
  "examples": [
    {"id":"e1","nl_statement":"plain-language example a human can confirm",
     "input_spec":{"generator":"solid","params":{"color":[0,0,0],"h":2,"w":2}},
     "args":{"color_highlights":"#0000ff","gamma":1.0},
     "expectation":{"kind":"literal","statement":"...", "literal":[r,g,b]}}
  ],
  "invariants": ["output stays in [0,1]", "output shape equals input shape"],
  "edge_cases": ["what happens at threshold boundaries", "..."]
}
Give 3 to 6 examples. Make at least one a clear anchor 'literal' when the op has natural
endpoints. Keep fixtures tiny (2x2 to 8x8). For a 'literal' whose output is uniform, you
may give a single pixel value [r,g,b] -- it will be broadcast."""
# NOTE: unpinned-axis discovery is NOT done here. Embedding a forced-enumeration in
# elaborate blew the token budget (truncated JSON) and over-listed. Axes come from
# the dedicated, conservative audit_unpinned_axes() pass below, and they drive ONLY
# stance generation -- they never enter elaborate's output, ref0, or the battery.


_AUDIT_SYSTEM = """You are a CONSERVATIVE spec auditor for a ComfyUI node-authoring \
agent. You receive an elaborated spec (operation, input/output types, confirmed \
examples, invariants). Find the FEW genuinely-consequential ambiguities: an input on \
which two competent engineers would ship implementations that BOTH satisfy every \
confirmed example/invariant yet produce a CLEARLY DIFFERENT output on a typical image.

Be strict. Most well-specified asks have ZERO or ONE such axis. Do NOT list:
- micro-decisions invisible on a normal image (kernel-size rounding, padding mode, \
  internal colour space, clamp ordering) -- these are not user-facing ambiguities;
- anything a confirmed example, invariant, contract formula, or an existing widget \
  already decides;
- more than the TWO highest-impact axes. If in doubt, omit it.

Only a difference a user would SEE and CARE about counts: a different OUTPUT SIZE, a \
different STRUCTURE, or a grossly different LOOK -- not an internal implementation detail.

CALIBRATION (match this exactly -- the hard part is catching a real under-specified \
TARGET while ignoring micro-decisions and aesthetic-look choices):

  ASK: "resize/make the image smaller"  (no target size stated)
  -> [{"axis":"target_size","dimension":"shape","interpretations":[
        "scale to half the input height and width",
        "scale the long edge to a fixed size (e.g. 512), keeping aspect",
        "scale by a user-provided factor widget"]}]
     RATIONALE: the user said "smaller" but NOT by how much -- two engineers ship \
     visibly different output sizes. This IS a real ambiguity. ALWAYS catch this class \
     (an under-specified output dimension/amount/target).

  ASK: "invert the colors, output = 1 - input"
  -> []   RATIONALE: the formula fully determines the output. Nothing to ask.

  ASK: "duotone look: map brightness to a gradient between two colors"
  -> []   RATIONALE: an aesthetic LOOK whose defining behavior is given. The exact \
     midtone ramp is a stylistic micro-choice, NOT a user-facing ambiguity -- do NOT ask.

So: CATCH an under-specified output size / amount / count / structural target. IGNORE \
internal details (padding, kernel rounding, colour space, clamp order) and aesthetic \
ramp shapes. Most asks are like invert/duotone -> [].

For each kept axis output one item:
  "axis": short snake_case name
  "dimension": "shape"|"value"|"channel"|"dtype"  (where the difference shows up)
  "interpretations": 2-4 distinct, both-defensible readings

Output ONLY a JSON array (at most 2 items), no markdown fences, no prose.
Output [] if the spec is fully pinned -- the COMMON answer for well-specified asks."""


def _strip_fences(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text


# ---------------------------------------------------------------------------
# helpers for unpinned-axes filtering
# ---------------------------------------------------------------------------

# Patterns that signal the spec already pins output shape with a CONCRETE
# commitment. Deliberately NARROW: bare words like "shape"/"resolution"/"output
# shape" do NOT count -- "output shape is smaller than input" leaves the size
# unpinned (smaller by how much?), so the shape axis must survive and escalate.
# Only a concrete relationship (explicit dims, //N, half-the-X, same/equal/preserve
# shape, a literal WxH) drops a shape axis. (Favor asking over silently banking.)
_SHAPE_PIN_RE = re.compile(
    r"\[\s*B?\s*,?\s*H"                                          # explicit [B,H,W,C] dims
    r"|//\s*\d"                                                  # H//2 etc.
    # "half the input/size/..." pins SHAPE only when NOT modifying a value noun
    # ("half the input PIXEL VALUE" is a brightness op, not a resize).
    r"|half\s+(?:the\s+)?(?:input|size|height|width|resolution|dimension)"
    r"(?!\s+(?:pixel|value|colou?r|intensit|brightness|luminance))"
    r"|same\s+(?:shape|size|resolution|dimension)"
    r"|(?:equals?|preserv\w+|unchanged|identical)\s+(?:the\s+)?(?:input\s+)?"
    r"(?:shape|size|resolution|dimension)"
    r"|\b\d{2,4}\s*[x×]\s*\d{2,4}\b",                       # concrete 512x512
    re.IGNORECASE,
)

# Patterns that signal channel layout is COMMITTED (not merely mentioned). Bare
# "channel"/"alpha" appear constantly in normal IMAGE-op prose ("the red channel
# of the output", "no channel dimension"), so requiring a commitment avoids
# silently dropping a real channel-count ambiguity.
_CHANNEL_PIN_RE = re.compile(
    r"\bRGBA?\b|\bC\s*=\s*[34]\b"
    r"|(?:always|only|preserv\w+|equals?|output|keep|maintain\w*)\s+"
    r"(?:the\s+)?(?:\w+\s+){0,2}(?:alpha|channels?)",
    re.IGNORECASE,
)


def _filter_pinned_axes(spec, axes):
    """Drop any axis already constrained by confirmed examples or invariants.

    Rules (kept simple and documented):
    - dimension=="shape": dropped if any invariant OR example statement mentions
      an explicit output shape (regex: _SHAPE_PIN_RE).
    - dimension=="channel": dropped if any invariant/example names channels/RGB/alpha
      (_CHANNEL_PIN_RE).
    - dimension=="value": dropped if any example statement mentions the axis keyword
      OR a widget for it exists in spec.input_types (widget presence = value is
      already user-settable, not an ambiguity).
    - dimension=="dtype": no heuristic -- always kept (dtype rarely appears in prose).
    When unsure, KEEP the axis (favor asking over silently banking).
    De-duplication by axis name applied at the end.
    """
    # Collect all prose text from invariants + example statements
    all_text = " ".join(spec.invariants)
    for e in spec.examples:
        all_text += " " + e.nl_statement
        all_text += " " + e.expectation.statement

    # Collect all declared widget names (keys in required + optional)
    widget_names = set()
    for bucket in ("required", "optional"):
        widget_names.update(spec.input_types.get(bucket, {}).keys())

    shape_pinned = bool(_SHAPE_PIN_RE.search(all_text))
    channel_pinned = bool(_CHANNEL_PIN_RE.search(all_text))

    seen_axes = set()
    result = []
    for ax in axes:
        if not isinstance(ax, dict):
            continue
        name = ax.get("axis", "")
        dim = ax.get("dimension", "")

        # Guard malformed entries: a null/empty axis name would crash re.escape /
        # name.lower() below and (caught upstream) silently void all filtering.
        if not name or not isinstance(name, str):
            continue

        # De-dup
        if name in seen_axes:
            continue
        seen_axes.add(name)

        # Shape gate
        if dim == "shape" and shape_pinned:
            continue

        # Channel gate
        if dim == "channel" and channel_pinned:
            continue

        # Value gate: drop if any TOKEN of the axis name overlaps a widget name or
        # appears in spec prose. Token-overlap (not exact match) so an axis like
        # "radius_sigma_mapping" is pruned by a "radius" widget or prose mention.
        if dim == "value":
            tokens = {t for t in re.split(r"[_\s]+", name.lower()) if len(t) > 2}
            widget_tokens = set()
            for wn in widget_names:
                widget_tokens.update(t for t in re.split(r"[_\s]+", wn.lower()) if len(t) > 2)
            text_lc = all_text.lower()
            if (tokens & widget_tokens) or any(t in text_lc for t in tokens):
                continue

        result.append(ax)

    # Hard cap: at most 2 axes survive (the audit is told the same; this is the
    # deterministic backstop against over-listing -- v0.2 probes one axis anyway).
    return result[:2]


def audit_unpinned_axes(ask, spec, model="claude-sonnet-4-6", client=None, max_tokens=700):
    """Adversarial second pass: fresh isolated call that sees the confirmed spec.

    Returns a list of axis dicts (same shape as unpinned_axes). Tolerates
    empty/garbage output -> returns []. Never raises (callers catch exceptions
    and fall back to the model's original list).
    """
    client = client or keys.anthropic_client()
    spec_text = spec.to_spec_string()
    user = (f"SPEC:\n\n{spec_text}\n\n"
            "List every axis where two competent engineers could differ. "
            "Output the JSON array now.")
    try:
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, temperature=0.2,
            system=[{"type": "text", "text": _AUDIT_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        raw = _strip_fences("".join(b.text for b in resp.content if b.type == "text"))
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            # Validate each item minimally; drop malformed ones
            valid = []
            for item in parsed:
                if (isinstance(item, dict) and isinstance(item.get("axis"), str)
                        and item.get("axis") and item.get("dimension")):
                    valid.append(item)
            return valid
        return []
    except Exception as exc:  # noqa: BLE001
        print(f"[NodeForge/spec] audit_unpinned_axes failed (non-fatal): {exc}")
        return []


def elaborate(ask, model="claude-sonnet-4-6", client=None):
    """Vague ask -> (records.Spec (unconfirmed), usage). Raises on unparseable output."""
    client = client or keys.anthropic_client()
    # A richly-specified ask (many examples + edge cases) can overrun the cap and
    # come back as truncated/unterminated JSON. Give it room (8000) AND retry on a
    # truncated or unparseable draw instead of crashing -- a spec this expensive to
    # discard is worth one more draw (mirrors benchmark/generate.py's truncation
    # guard, here softened to a retry because elaborate is the entry point).
    d = None
    last_err = None
    resp = None
    for attempt in range(2):
        resp = client.messages.create(
            model=model, max_tokens=8000, temperature=0.3,
            system=[{"type": "text", "text": _SPEC_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"ASK: {ask}\n\nProduce the JSON spec now."}],
        )
        raw = _strip_fences("".join(b.text for b in resp.content if b.type == "text"))
        if resp.stop_reason == "max_tokens":
            last_err = "spec JSON truncated at max_tokens=8000"
            continue
        try:
            d = json.loads(raw)
            break
        except json.JSONDecodeError as e:
            last_err = f"spec JSON unparseable ({e})"
            continue
    if d is None:
        raise ValueError(f"elaborate: no valid spec JSON after 2 tries ({last_err})")
    examples = []
    for i, e in enumerate(d.get("examples", [])):
        examples.append(records.Example(
            id=e.get("id", f"e{i+1}"),
            nl_statement=e["nl_statement"],
            input_spec=records.InputSpec.from_dict(e["input_spec"]),
            expectation=records.Expectation.from_dict(e["expectation"]),
            args=e.get("args", {}) or {},
        ))
    spec = records.Spec(
        ask=ask, title=d.get("title", ask[:40]),
        input_types=d.get("input_types", {"required": {"image": ["IMAGE"]}}),
        return_types=d.get("return_types", ["IMAGE"]),
        return_names=d.get("return_names"),
        contract=d.get("contract", ""),
        examples=examples,
        invariants=d.get("invariants", []),
        edge_cases=d.get("edge_cases", []),
        confirmed=False,
    )
    # v0.2 ambiguity oracle: axes come ONLY from the dedicated conservative audit
    # (the elaborate-embedded enumeration blew the token budget + over-listed). The
    # deterministic filter prunes already-pinned axes and caps the count. Any failure
    # is non-fatal -> no axes -> the loop behaves exactly as v0.1.
    try:
        audit_axes = audit_unpinned_axes(ask, spec, model=model, client=client)
        spec.unpinned_axes = _filter_pinned_axes(spec, audit_axes)
    except Exception as exc:  # noqa: BLE001
        print(f"[NodeForge/spec] unpinned-axis discovery failed (non-fatal): {exc}")
        spec.unpinned_axes = []
    return spec, resp.usage
