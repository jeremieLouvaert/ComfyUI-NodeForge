"""
Stage 1 -- human confirms the spec (the cheap semantic oracle).

Presents the elaborated spec in plain language: what the node does, its inputs and
outputs, and the 3-6 confirmed examples + invariants. NO CODE is shown -- intent
is pinned here, before any implementation exists. For image ops the INPUT fixture
of each example can be rendered to a thumbnail (best-effort, via the sandbox).

Two modes:
  - interactive (default): print the spec, then a menu to accept / drop an example
    / add a free-text invariant / abort.
  - auto: accept as-is (used by the scripted acceptance tests); optional `edits`
    dict can drop examples or append invariants non-interactively.
"""
import os

from . import sandbox


class AbortError(Exception):
    pass


def render_input_thumbnails(spec, out_dir):
    """Best-effort: render each example's INPUT fixture to a PNG via the sandbox.
    Returns {example_id: png_path}. Never raises (rendering is a nicety)."""
    try:
        os.makedirs(out_dir, exist_ok=True)
        fixtures = [{"example_id": e.id, "input_spec": e.input_spec.to_dict()} for e in spec.examples]
        rendered = sandbox.render(fixtures, out_dir)
        return {k[len("in_"):]: v for k, v in rendered.items() if k.startswith("in_")}
    except Exception:
        return {}


def format_spec(spec, thumbs=None):
    L = ["=" * 70, f"NodeForge wants to build: {spec.title}", "=" * 70,
         f"\nYour ask:\n  {spec.ask}\n", "Inputs:"]
    req = spec.input_types.get("required", {})
    opt = spec.input_types.get("optional", {})
    for k, v in {**req, **opt}.items():
        t = v[0] if isinstance(v, (list, tuple)) and v else v
        extra = ""
        if isinstance(v, (list, tuple)) and len(v) > 1 and isinstance(v[1], dict) and "default" in v[1]:
            extra = f" (default {v[1]['default']})"
        L.append(f"  - {k}: {t}{extra}")
    rnames = spec.return_names or spec.return_types
    L.append("Outputs:")
    for n, t in zip(rnames, spec.return_types):
        L.append(f"  - {n}: {t}")
    if spec.contract:
        L.append(f"\nContract: {spec.contract}")
    L.append("\nExamples (these become the trusted test -- confirm they are what you mean):")
    for i, e in enumerate(spec.examples):
        L.append(f"  [{i}] {e.nl_statement}")
        if thumbs and e.id in thumbs:
            L.append(f"       input preview: {thumbs[e.id]}")
    L.append("\nInvariants the node must always satisfy:")
    for i, inv in enumerate(spec.invariants):
        L.append(f"  ({i}) {inv}")
    if spec.edge_cases:
        L.append("\nEdge cases noted:")
        for ec in spec.edge_cases:
            L.append(f"  - {ec}")
    L.append("")
    return "\n".join(L)


def confirm_spec(spec, interactive=True, render_dir=None, edits=None, inp=input, out=print):
    """Return a confirmed Spec (confirmed=True) or raise AbortError. `edits` (auto
    mode): {"drop":[ids], "add_invariants":[str]}."""
    thumbs = render_input_thumbnails(spec, render_dir) if render_dir else None
    out(format_spec(spec, thumbs))

    if not interactive:
        if edits:
            drop = set(edits.get("drop", []))
            spec.examples = [e for e in spec.examples if e.id not in drop]
            spec.invariants = list(spec.invariants) + list(edits.get("add_invariants", []))
        spec.confirmed = True
        return spec

    while True:
        out("\nConfirm this spec?  [y]es  [d N] drop example N  [i] add invariant  [a]bort")
        choice = inp("> ").strip().lower()
        if choice in ("y", "yes", ""):
            spec.confirmed = True
            return spec
        if choice.startswith("d"):
            parts = choice.split()
            if len(parts) > 1 and parts[1].isdigit():
                idx = int(parts[1])
                if 0 <= idx < len(spec.examples):
                    dropped = spec.examples.pop(idx)
                    out(f"dropped example [{idx}]: {dropped.nl_statement}")
            out(format_spec(spec, thumbs))
        elif choice.startswith("i"):
            text = inp("new invariant: ").strip()
            if text:
                spec.invariants.append(text)
            out(format_spec(spec, thumbs))
        elif choice.startswith("a"):
            raise AbortError("human aborted at Stage 1")
        else:
            out("unrecognized choice")
