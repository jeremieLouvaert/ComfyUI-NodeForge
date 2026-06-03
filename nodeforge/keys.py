"""
API-key resolution, following the AKURATE convention (CLAUDE.md):
env var first, then a {service}_api_key.txt in the ComfyUI root.

Never logs or returns the key anywhere except to the anthropic client.
"""
import os

def _default_comfy_root():
    """ComfyUI base dir, derived at runtime (portable). Prefer ComfyUI's folder_paths
    in-process, else this pack's location. Override: NODEFORGE_COMFY_ROOT."""
    try:
        import folder_paths
        return folder_paths.base_path
    except Exception:
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.dirname(os.path.dirname(os.path.dirname(here)))


_COMFY_ROOT = os.environ.get("NODEFORGE_COMFY_ROOT") or _default_comfy_root()


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


# Transient-error resilience: the SDK already retries 429/500/502/503/529 with
# exponential backoff; the default of 2 is too few during an Anthropic overload
# (a real mid-author 529 should wait it out, not crash the run). 8 retries buys
# ~a couple of minutes of backoff before giving up. Centralized here so every
# stage that builds its client via this helper inherits it.
MAX_RETRIES = 8
TIMEOUT_S = 120.0


def anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=anthropic_key(),
                               max_retries=MAX_RETRIES, timeout=TIMEOUT_S)


# Newer models (e.g. claude-opus-4-8) DEPRECATE the `temperature` param and 400 on
# it. The engine sets temperature on most calls (diversity for impls/mutants), so
# wrap creation: drop temperature + retry on that specific 400, and remember the
# model so the rest of the run skips it (one wasted request per model, not per call).
_NO_TEMPERATURE = set()


def create_message(client, **kwargs):
    model = kwargs.get("model")
    if model in _NO_TEMPERATURE:
        kwargs.pop("temperature", None)
    try:
        return client.messages.create(**kwargs)
    except Exception as e:
        if "temperature" in str(e).lower() and "temperature" in kwargs:
            _NO_TEMPERATURE.add(model)
            kwargs.pop("temperature", None)
            return client.messages.create(**kwargs)
        raise
