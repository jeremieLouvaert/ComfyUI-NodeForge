"""
API-key resolution, following the AKURATE convention (CLAUDE.md):
env var first, then a {service}_api_key.txt in the ComfyUI root.

Never logs or returns the key anywhere except to the anthropic client.
"""
import os

_COMFY_ROOT = os.environ.get(
    "NODEFORGE_COMFY_ROOT",
    r"F:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\ComfyUI",
)


def anthropic_key():
    """Return the Anthropic API key from env or anthropic_api_key.txt, or raise a
    clear error pointing at both options."""
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k:
        return k.strip()
    path = os.path.join(_COMFY_ROOT, "anthropic_api_key.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            v = f.read().strip()
        if v:
            return v
    raise RuntimeError(
        "No Anthropic API key. Set ANTHROPIC_API_KEY, or create "
        f"{path} with the key as its only contents."
    )


def anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=anthropic_key())
