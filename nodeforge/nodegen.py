"""
Wrap an approved implementation into a full, installable ComfyUI node pack.

Mirrors the proven probe/ComfyUI-Node-Probe/ layout exactly:
  ComfyUI-NodeForge-<Title>/
    __init__.py            (re-exports NODE_CLASS_MAPPINGS + NODE_DISPLAY_NAME_MAPPINGS)
    nodes/
      __init__.py          (subpackage marker)
      <key>.py             (the verified node module + the two mappings)

Approach: the approved candidate's source is ALREADY a complete, verified, working
node module (it passed the whole battery in the sandbox, including any module-level
helpers it defines). So we ship it VERBATIM rather than surgically extracting the
method (which would silently drop module-level helper functions). We only:
  - force CATEGORY = "AKURATE/NodeForge" on the node class,
  - strip any NODE_*_MAPPINGS the candidate emitted, and
  - append our own mappings keyed by the candidate's real class name, with the
    human-facing display name = spec.title.
The verified class keeps its own FUNCTION/INPUT_TYPES/RETURN_TYPES (they satisfy
the spec by construction -- that is what the battery checked).
"""
import os
import re
import shutil

_CATEGORY = "AKURATE/NodeForge"


def _pascal(title):
    parts = re.split(r"[^0-9A-Za-z]+", title)
    name = "".join(p[:1].upper() + p[1:] for p in parts if p)
    if not name:
        name = "NodeForgeNode"
    if name[0].isdigit():
        name = "N" + name
    return name


def _candidate_class_name(source, fallback):
    """The node class the candidate defines (the one carrying FUNCTION)."""
    # the class immediately above a `FUNCTION = "..."` line is the node class;
    # simplest robust heuristic: the last top-level class defined.
    names = re.findall(r"^class\s+([A-Za-z_]\w*)", source, re.MULTILINE)
    return names[-1] if names else fallback


def _strip_mappings(source):
    """Remove any NODE_CLASS_MAPPINGS / NODE_DISPLAY_NAME_MAPPINGS assignment
    blocks the candidate emitted (we append our own)."""
    out, lines, i = [], source.splitlines(), 0
    while i < len(lines):
        if re.match(r"^(NODE_CLASS_MAPPINGS|NODE_DISPLAY_NAME_MAPPINGS)\s*=", lines[i]):
            # skip until the assignment's brackets balance
            depth = lines[i].count("{") - lines[i].count("}")
            i += 1
            while i < len(lines) and depth > 0:
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out).rstrip()


def _force_category(source):
    """Set CATEGORY = "AKURATE/NodeForge" on the class (replace if present, else the
    caller appends one). Returns (source, had_category)."""
    new, n = re.subn(r"""(\n\s*)CATEGORY\s*=\s*['"][^'"]*['"]""",
                     rf"""\1CATEGORY = "{_CATEGORY}\"""", source, count=1)
    return new, (n > 0)


def build_node_source(spec, candidate, class_name=None):
    """Produce the full <key>.py module text. Returns (module_source, class_name)
    where class_name is the candidate's REAL node class (used as the mapping key)."""
    src = candidate.source.strip()
    real_cls = _candidate_class_name(src, candidate.class_name)
    src = _strip_mappings(src)
    src, had_cat = _force_category(src)
    if not had_cat:
        # inject a CATEGORY right after the class's RETURN_TYPES or FUNCTION line
        src = re.sub(r"(\n(\s*)FUNCTION\s*=\s*['\"]\w+['\"])",
                     rf"""\1\n\2CATEGORY = "{_CATEGORY}\"""", src, count=1)
    header = f'"""Authored + verified by NodeForge. Spec: {spec.title}."""\n'
    mappings = (f'\n\nNODE_CLASS_MAPPINGS = {{{real_cls!r}: {real_cls}}}\n'
                f'NODE_DISPLAY_NAME_MAPPINGS = {{{real_cls!r}: {spec.title!r}}}\n')
    return header + src + mappings, real_cls


def write_pack(spec, candidate, staging_root, pack_name=None, class_name=None):
    """Write the full pack to staging_root/<pack_name>/. Returns (pack_dir,
    class_name, display_name)."""
    node_src, real_cls = build_node_source(spec, candidate, class_name)
    key = class_name or _pascal(spec.title)
    pack_name = pack_name or f"ComfyUI-NodeForge-{key}"
    pack_dir = os.path.join(staging_root, pack_name)
    nodes_dir = os.path.join(pack_dir, "nodes")
    os.makedirs(nodes_dir, exist_ok=True)

    with open(os.path.join(nodes_dir, f"{key}.py"), "w", encoding="utf-8") as f:
        f.write(node_src)
    with open(os.path.join(nodes_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(f"# subpackage marker for {pack_name}\n")
    init = (f"from .nodes.{key} import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS\n\n"
            f'__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]\n\n'
            f'print(f"[NodeForge] loaded {{len(NODE_CLASS_MAPPINGS)}} node(s): '
            f'{{\', \'.join(NODE_CLASS_MAPPINGS)}}")\n')
    with open(os.path.join(pack_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(init)
    return pack_dir, real_cls, spec.title
