"""
Build / refresh the CORE-node index for the NodeForge retrieval stage (the v0.2
core-node path).

The custom-pack index (build_index.py) has NO core nodes, so asks answered by a
ComfyUI built-in either misdirect to a custom wrapper pack (the row-15 SD3
failure) or route to authoring a redundant node. This snapshots the canonical
CORE node set so retrieval can answer "ComfyUI already ships this: <NodeName>".

Source of truth (D1): the ComfyUI source registry itself, scoped to CORE only.
`import nodes` registers the base nodes; `init_builtin_extra_nodes()` adds
comfy_extras. Neither loads custom_nodes (that is init_external_custom_nodes,
called only by init_extra_nodes(init_custom_nodes=True)) -- so the resulting
NODE_CLASS_MAPPINGS is core + comfy_extras with ZERO custom contamination
(separation confirmed in nodes.py: load_custom_node / init_external_custom_nodes
are a distinct path). API nodes are deliberately excluded (paid Comfy-API
wrappers, not built-in ops).

This is a one-time snapshot build (heavy ComfyUI import), NOT on the retrieval
hot path. The snapshot is version-stamped and regenerable; retrieval reads the
JSON. Re-run after a ComfyUI update.

Run with the EMBEDDED python (it has torch + ComfyUI's deps):
    F:/.../python_embeded/python.exe eval/build_core_index.py
"""
import os
import sys
import json
import time
import asyncio

# Default ComfyUI location (CLAUDE.md PROJECT IDENTITY). Override with --comfy.
DEFAULT_COMFY = r"F:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\ComfyUI"

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "index_cache")
OUT = os.path.join(CACHE_DIR, "core_nodes.json")

# Socket type tokens worth recording as capability signal (uppercase data types).
# Combo inputs (python lists of enum values) are skipped -- they are widget
# choices, not a capability signal.
def _io_type(t):
    """Return a type token string for an input/output spec, or None to skip."""
    if isinstance(t, str):
        return t
    return None  # list = combo/enum widget; dict/other = skip


def _input_signal(cls):
    """Extract input socket type tokens + param names from INPUT_TYPES().
    Wrapped: some core nodes hit the filesystem (model lists) and can raise."""
    names, types = [], []
    try:
        spec = cls.INPUT_TYPES()
    except Exception:
        return names, types
    for section in ("required", "optional"):
        for pname, pspec in (spec.get(section) or {}).items():
            names.append(pname)
            # pspec is typically (TYPE, {opts}) or (TYPE,) or [choices]
            if isinstance(pspec, (list, tuple)) and pspec:
                tok = _io_type(pspec[0])
                if tok:
                    types.append(tok)
    return names, types


def _comfy_version(comfy_root):
    """Best-effort ComfyUI version stamp from comfyui_version.py, else 'unknown'."""
    try:
        ns = {}
        with open(os.path.join(comfy_root, "comfyui_version.py"), encoding="utf-8") as f:
            exec(f.read(), ns)
        return ns.get("__version__", "unknown")
    except Exception:
        return "unknown"


def build(comfy_root, now=None):
    now = time.time() if now is None else now
    if comfy_root not in sys.path:
        sys.path.insert(0, comfy_root)
    # ComfyUI modules resolve some relative paths against cwd; chdir to be safe.
    prev_cwd = os.getcwd()
    os.chdir(comfy_root)
    try:
        # Pin the CORRECT utils package in sys.modules before the extras load.
        # init_builtin_extra_nodes loads each comfy_extras file via load_custom_node,
        # which manipulates sys.path; a few newer extras do `from utils.install_util
        # import ...` and, without this, can resolve a stray non-package `utils`
        # ("'utils' is not a package") and silently fail to register.
        import utils.install_util  # noqa: F401
        import nodes  # registers base NODE_CLASS_MAPPINGS at import time
        # add comfy_extras (SD3, ControlNet-advanced, mask/compositing, ...); no custom, no api
        asyncio.run(nodes.init_builtin_extra_nodes())
        class_map = dict(nodes.NODE_CLASS_MAPPINGS)
        disp_map = dict(nodes.NODE_DISPLAY_NAME_MAPPINGS)
    finally:
        os.chdir(prev_cwd)

    entries = []
    for name, cls in class_map.items():
        in_names, in_types = _input_signal(cls)
        rt = getattr(cls, "RETURN_TYPES", ()) or ()
        rn = getattr(cls, "RETURN_NAMES", ()) or ()
        entries.append({
            "name": name,
            "display_name": disp_map.get(name, name),
            "category": getattr(cls, "CATEGORY", "") or "",
            "description": (getattr(cls, "DESCRIPTION", "") or "")[:400],
            "input_names": in_names,
            "input_types": sorted(set(in_types)),
            "output_types": list(rt),
            "output_names": list(rn),
            "output_node": bool(getattr(cls, "OUTPUT_NODE", False)),
            "source": "core",
        })
    entries.sort(key=lambda e: e["name"])
    os.makedirs(CACHE_DIR, exist_ok=True)
    rec = {
        "fetched_at": now,
        "comfyui_version": _comfy_version(comfy_root),
        "count": len(entries),
        "core_nodes": entries,
    }
    json.dump(rec, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return rec


def load_core_index():
    """Read the cached core-node index (list of entry dicts). [] if absent."""
    if not os.path.exists(OUT):
        return []
    try:
        return json.load(open(OUT, encoding="utf-8")).get("core_nodes", [])
    except Exception:
        return []


if __name__ == "__main__":
    comfy = DEFAULT_COMFY
    if "--comfy" in sys.argv:
        comfy = sys.argv[sys.argv.index("--comfy") + 1]
    rec = build(comfy)
    print(f"[core-index] ComfyUI {rec['comfyui_version']}: snapshotted {rec['count']} core nodes -> {OUT}")
    # spot-check the 5 backend core targets from the eval's core asks
    by_name = {e["name"]: e for e in rec["core_nodes"]}
    for n in ("ImageScale", "ImageToMask", "TripleCLIPLoader", "ModelSamplingSD3",
              "EmptySD3LatentImage", "ControlNetApply", "ControlNetApplyAdvanced"):
        e = by_name.get(n)
        print(f"   {'OK ' if e else 'MISS'} {n}"
              + (f"  [{e['category']}] {e['display_name']!r} out={e['output_types']}" if e else ""))
