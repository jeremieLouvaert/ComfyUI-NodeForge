"""
Stage 2 of the self-verification model: synthesize a verification battery from a
CONFIRMED spec, black-box (the generator never sees any implementation).

The generated module exposes:
    CHECKS          : list of functions, each check(NodeClass) -> (name, passed, detail)
    OPEN_QUESTIONS  : list of strings -- behavior the spec did NOT pin down (triage signal)

The harness (run_benchmark.py) imports the module and runs every check against
each implementation, owning the isolation (a raising check counts as failed).
"""
import os
import re
import anthropic


SYSTEM_PROMPT = """You are the verification stage of a ComfyUI node-authoring agent. \
You are given a CONFIRMED specification for a custom node -- a plain-language description \
plus input/output contract plus human-confirmed examples and invariants. You have NOT seen \
any implementation and you never will. Your job is to write an executable test battery that \
decides whether an arbitrary implementation of this spec is correct.

ComfyUI conventions:
- IMAGE tensor: torch.float32, shape [B, H, W, C], values in [0,1], C=3 (RGB).
- MASK tensor: torch.float32, shape [B, H, W], values in [0,1]. (NO channel dimension.)
- A node is a class with classmethod INPUT_TYPES(), RETURN_TYPES (tuple of type strings),
  optional RETURN_NAMES, FUNCTION (the method name as a string), CATEGORY. The method named
  by FUNCTION returns a tuple matching RETURN_TYPES.

FOUR ANTI-CIRCULARITY RULES (non-negotiable):
1. Author every check from the SPEC, never from guessing how the code is written. You are a
   black box to the implementation.
2. Prefer PROPERTIES, RELATIONS, and CONCRETE CONFIRMED EXAMPLES over recomputing an
   "expected output" with your own full reimplementation. Recomputing the whole operation is
   just a second implementation that can share the same blind spot. EXCEPTION: when the spec
   pins an exact formula or an exact concrete example, encoding THAT directly is encoding the
   spec, not guessing -- do it (e.g. a stated Rec.709 weighting, or "white in -> black out").
3. Every check must DISCRIMINATE: a plausible wrong implementation must fail at least one
   check. A vacuously-true assertion (one that passes no matter what) is worse than no check.
   Before you emit a check, ask yourself which realistic bug it would catch.
4. Do NOT assert behavior the spec leaves open. If the spec is silent or explicitly
   unspecified about something (e.g. an unspecified interpolation method), do NOT pin it with
   a check -- that would falsely reject valid implementations. Instead add it to OPEN_QUESTIONS.

CHOOSING TEST SIGNALS (this prevents false rejections of correct code):
Pick inputs that make the specified effect OBSERVABLE on a correct implementation. If the
operation clamps to a range (e.g. [0,1]), do NOT probe it only with fully-saturated inputs
(all 0s / all 1s, or a hard 0-vs-1 edge) -- a correct clamped op can legitimately show ZERO
change there because the effect is clipped away, and your check would falsely reject it. Use
mid-tone signals instead (values around 0.3-0.7, soft edges, gradients, or random textures)
so the effect is visible. Likewise prefer testing a property on inputs where it is actually
expected to hold. A check whose own probe input hides the effect is a bug in the check.

OUTPUT CONTRACT -- emit ONLY a Python module, no markdown fences, no prose. The module must:
- import torch (and torch.nn.functional as F, math if needed).
- define each check as a top-level function check_<name>(NodeClass) that:
    * instantiates the node: node = NodeClass()
    * gets the method: fn = getattr(node, NodeClass.FUNCTION)
    * builds its own test inputs (an IMAGE is torch.rand(B,H,W,3); use a fixed
      torch.Generator().manual_seed(...) for determinism)
    * calls fn(**inputs) with inputs keyed by the names in INPUT_TYPES
    * returns a 3-tuple (name: str, passed: bool, detail: str). Cast passed to a Python bool.
    * does its OWN narrow try/except only if needed; otherwise let exceptions propagate
      (the harness treats a raised check as failed).
- define CHECKS = [check_a, check_b, ...] (the list of your check functions).
- define OPEN_QUESTIONS = [...] (strings; empty list if the spec fully pins the behavior).

Write thorough, discriminating checks that cover the contract (type/shape/range) AND the
semantic behavior described by the examples and invariants."""


def _strip_fences(text):
    """Remove ```python ... ``` fences if the model added them despite instructions."""
    text = text.strip()
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def generate_battery(spec_text, model="claude-sonnet-4-6", max_tokens=8000, seed_hint=0):
    """Call Claude to synthesize a verification battery from the spec alone.
    seed_hint varies the prompt across trials so repeated calls explore variation.
    Returns the generated module source (str)."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user = (
        f"CONFIRMED SPEC (trial {seed_hint}):\n\n{spec_text}\n\n"
        "Write the verification module now. Output only the Python module."
    )
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user}],
    )
    usage = resp.usage
    if resp.stop_reason == "max_tokens":
        # Truncated output -> unterminated strings/brackets. Diagnose loudly rather
        # than letting it surface downstream as a mystery syntax error.
        raise ValueError(f"output truncated at max_tokens={max_tokens}; raise the cap")
    code = _strip_fences("".join(b.text for b in resp.content if b.type == "text"))
    return code, usage
