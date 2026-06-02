"""
The teeth-test mutation engine (self-verification-model.md section 9.2).

A generated check counts only if it FAILS on >=1 mutant AND PASSES ref0. This
module produces the mutants: plausibly-wrong implementations of the spec, used as
teeth targets. Per section 9.2 we mutate the BEHAVIOR, never a Stage-3 candidate's
code (that would share its blind spots). Two sources:

1. OPERATOR MUTANTS -- spec-agnostic output-corruption wrappers around ref0 (the
   Stage-2 reference impl, which is NOT a Stage-3 candidate, so no circularity).
   Each operator takes ref0's correct output and corrupts it one specific way,
   generalizing the five probe/negative_control.py bug classes:
     channel_permute  (R/G swap)            -> BadChannelShuffle
     mask_channeldim  ([B,H,W]->[B,H,W,1])  -> BadLumaMask_channeldim
     drop_clamp       (push out of [0,1])   -> a clamp/range bug
     scale_factor     (wrong magnitude)     -> wrong-factor family
     add_constant     (offset)              -> subtle value error
     zero_output      (kills the signal)    -> returns-blur / dead-output family
     identity         (returns the input)   -> no-op family
     transpose_hw     (swap H/W)            -> geometry error
   Operators are selected by the spec (mask_channeldim only when a MASK output
   exists; channel_permute only for a 3-channel IMAGE output; etc).

2. LLM SUBTLY-WRONG MUTANT -- one (or few) "implement this spec but with one
   subtle, realistic bug" generations in a context SEPARATE from both the
   check-author (synth/generate.py) and the implementer (codegen.py), preserving
   anti-circularity rule 1. Catches operation-specific bugs the static operators
   cannot express (wrong luma coefficients, off-by-one, global-vs-local, sign
   flips), which is exactly the negative_control "avg not Rec.709" / "not lossless"
   family.

A mutant counts as a valid teeth target only if it LOADS and returns a tensor of
the declared RETURN_TYPES on the basic fixture AND its output actually differs
from ref0. That validation is done in the sandbox by the caller (synth.py); this
module only emits sources.
"""
import os
import re

from . import records


# ---------------------------------------------------------------------------
# operator corruption snippets -- each returns code that mutates `_out` (a list
# of output tensors) in place, given the integer output index to hit.
# ---------------------------------------------------------------------------
def _op_channel_permute(i):  return f"_out[{i}] = _out[{i}][..., [1, 0, 2]].contiguous()"
def _op_mask_channeldim(i):  return f"_out[{i}] = _out[{i}].unsqueeze(-1)"
def _op_drop_clamp(i):       return f"_out[{i}] = _out[{i}] * 1.4"          # pushes > 1 for bright pixels
def _op_scale_factor(i):     return f"_out[{i}] = _out[{i}] * 0.5"
def _op_add_constant(i):     return f"_out[{i}] = (_out[{i}] + 0.13).clamp(0, 1)"
def _op_zero_output(i):      return f"_out[{i}] = torch.zeros_like(_out[{i}])"
def _op_identity(i):         return f"_out[{i}] = kwargs.get('image', _out[{i}])"
def _op_transpose_hw(i):     return f"_out[{i}] = _out[{i}].transpose(1, 2).contiguous()"


def _image_indices(return_types):
    return [i for i, t in enumerate(return_types) if t == "IMAGE"]


def _mask_indices(return_types):
    return [i for i, t in enumerate(return_types) if t == "MASK"]


def _select_operators(spec):
    """Pick applicable operators for this spec. Returns [(op_name, snippet_code)]."""
    rt = list(spec.return_types)
    imgs = _image_indices(rt)
    masks = _mask_indices(rt)
    ops = []
    primary = imgs[0] if imgs else (masks[0] if masks else 0)
    if imgs:
        ops.append(("channel_permute", _op_channel_permute(imgs[0])))
    if masks:
        ops.append(("mask_channeldim", _op_mask_channeldim(masks[0])))
    ops.append(("drop_clamp", _op_drop_clamp(primary)))
    ops.append(("scale_factor", _op_scale_factor(primary)))
    ops.append(("add_constant", _op_add_constant(primary)))
    ops.append(("zero_output", _op_zero_output(primary)))
    ops.append(("transpose_hw", _op_transpose_hw(primary)))
    if imgs:
        ops.append(("identity", _op_identity(imgs[0])))
    return ops


_MUTANT_TEMPLATE = '''\
{ref0_source}


class {mut_class}:
    @classmethod
    def INPUT_TYPES(cls):
        return {input_types!r}
    RETURN_TYPES = {return_types!r}
{return_names_line}    FUNCTION = "execute"
    CATEGORY = "NFMUT"
    def execute(self, **kwargs):
        _ref = {ref0_class}()
        _fn = getattr(_ref, {ref0_class}.FUNCTION)
        _out = _fn(**kwargs)
        if not isinstance(_out, tuple):
            _out = (_out,)
        _out = list(_out)
        {corruption}
        return tuple(_out)
'''


def build_operator_mutants(spec, ref0_source, ref0_class):
    """One Candidate per applicable operator, each wrapping ref0 and corrupting
    its output. `torch` is available because ref0_source imports it."""
    rnames = spec.return_names
    rline = f"    RETURN_NAMES = {tuple(rnames)!r}\n" if rnames else ""
    mutants = []
    for op_name, corruption in _select_operators(spec):
        mut_class = f"NFMutant_{op_name}"
        src = _MUTANT_TEMPLATE.format(
            ref0_source=ref0_source.strip(),
            mut_class=mut_class,
            input_types=spec.input_types,
            return_types=tuple(spec.return_types),
            return_names_line=rline,
            ref0_class=ref0_class,
            corruption=corruption,
        )
        mutants.append(records.Candidate(
            id=f"mutant_op:{op_name}", source=src, class_name=mut_class,
            origin=f"mutant_op:{op_name}"))
    return mutants


# ---------------------------------------------------------------------------
# LLM subtly-wrong mutant (isolated context)
# ---------------------------------------------------------------------------
_MUTANT_SYSTEM = """You are a code-mutation tool used to TEST a verification battery. \
Given a ComfyUI custom-node specification, write a COMPLETE implementation that looks \
correct and plausible but contains exactly ONE subtle, realistic bug -- the kind a \
competent developer might actually ship by mistake (a wrong luma coefficient, an \
off-by-one in a threshold or slice, a global reduction where a local one was meant, a \
sign or order swap, a missing clamp). Do NOT make it obviously broken (no syntax errors, \
no crashes, correct INPUT_TYPES/RETURN_TYPES/FUNCTION/CATEGORY, returns the declared \
types and shapes). The bug must be in the BEHAVIOR.

ComfyUI conventions:
- IMAGE tensor: torch.float32, shape [B, H, W, C], values in [0,1], C=3 (RGB).
- MASK tensor: torch.float32, shape [B, H, W], values in [0,1] (NO channel dimension).
- A node is a class with classmethod INPUT_TYPES(), RETURN_TYPES (tuple of type strings),
  optional RETURN_NAMES, FUNCTION (method name as a string), CATEGORY, and the method.

Output ONLY a Python module: imports + one node class. No markdown fences, no prose, no
comment naming the bug."""


def _strip_fences(text):
    text = text.strip()
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text


def _first_node_class_name(source):
    names = re.findall(r"^class\s+([A-Za-z_]\w*)", source, re.MULTILINE)
    return names[0] if names else "Node"


def build_llm_mutants(spec, n=1, model="claude-sonnet-4-6", client=None):
    """Generate n subtly-wrong implementations from the spec in an isolated
    context. Returns [Candidate]. Requires ANTHROPIC_API_KEY (or a passed client)."""
    import anthropic
    client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                                            max_retries=8, timeout=120)
    spec_text = spec.to_spec_string()
    out = []
    for k in range(n):
        user = (f"SPECIFICATION (mutation seed {k}):\n\n{spec_text}\n\n"
                "Write the subtly-buggy implementation now. Output only the Python module.")
        resp = client.messages.create(
            model=model, max_tokens=4000, temperature=1.0,
            system=[{"type": "text", "text": _MUTANT_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        if resp.stop_reason == "max_tokens":
            continue  # truncated mutant = broken source; mutants are optional, skip it
        src = _strip_fences("".join(b.text for b in resp.content if b.type == "text"))
        cname = _first_node_class_name(src)
        out.append(records.Candidate(id=f"mutant_llm:{k}", source=src,
                                     class_name=cname, origin="mutant_llm"))
    return out
