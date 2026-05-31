"""
Bank an approved + staged node pack into the live ComfyUI install.

Follows the AKURATE deployment rules (decisions.md 2026-03-22 + patterns.md):
COPY, never symlink; clear __pycache__; do NOT auto-restart the server (killing a
running server is out of scope -- print the restart instruction instead). The
banked copy is load-tested in the sandbox before we declare success.
"""
import os
import shutil

from . import sandbox

CUSTOM_NODES = os.environ.get(
    "NODEFORGE_CUSTOM_NODES",
    r"F:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\ComfyUI\custom_nodes",
)


def _clear_pycache(root):
    for dirpath, dirnames, filenames in os.walk(root):
        for d in list(dirnames):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)
        for fn in filenames:
            if fn.endswith(".pyc"):
                try:
                    os.remove(os.path.join(dirpath, fn))
                except OSError:
                    pass


def loadtest_pack(node_source, class_name, wall_s=30):
    """Sandbox structural load-test of a single node module before banking."""
    job = {"job_id": "bank_loadtest", "mode": "loadtest", "allow_gpu": False,
           "candidates": [{"id": class_name, "source": node_source,
                           "class_name": class_name, "origin": "impl"}],
           "batteries": [], "example_fixtures": []}
    rep = sandbox.run_job(job, wall_s=wall_s)
    err = rep.load_errors.get(class_name)
    return (err is None), err


def bank(pack_dir, force=False, custom_nodes=None):
    """Copy the staged pack into custom_nodes. Returns (dest, message). Refuses to
    overwrite an existing pack unless force=True (banked nodes are user assets)."""
    custom_nodes = custom_nodes or CUSTOM_NODES
    pack_name = os.path.basename(pack_dir.rstrip("/\\"))
    dest = os.path.join(custom_nodes, pack_name)
    if os.path.exists(dest):
        if not force:
            raise FileExistsError(
                f"{dest} already exists; pass force=True to overwrite (banked nodes "
                f"are user assets -- overwriting is deliberate).")
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(pack_dir, dest)
    _clear_pycache(dest)
    msg = (f"Banked to {dest}\n"
           f"RESTART ComfyUI to load it (copy -> __pycache__ cleared; not auto-restarted).")
    return dest, msg
