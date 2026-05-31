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


def _strip_fences(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text


def elaborate(ask, model="claude-sonnet-4-6", client=None):
    """Vague ask -> (records.Spec (unconfirmed), usage). Raises on unparseable output."""
    client = client or keys.anthropic_client()
    resp = client.messages.create(
        model=model, max_tokens=2000, temperature=0.3,
        system=[{"type": "text", "text": _SPEC_SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"ASK: {ask}\n\nProduce the JSON spec now."}],
    )
    raw = _strip_fences("".join(b.text for b in resp.content if b.type == "text"))
    d = json.loads(raw)
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
    return spec, resp.usage
