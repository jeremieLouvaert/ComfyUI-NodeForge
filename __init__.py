"""
ComfyUI-NodeForge -- a node-authoring copilot, surfaced as a ComfyUI sidebar
PANEL (not a graph node: ComfyUI has no pause-for-editorial-review primitive).

This pack registers ZERO graph nodes. It contributes:
  - backend HTTP routes under /nodeforge/* (nodeforge/server_routes.py), which
    drive the proven author -> verify -> bank engine and stream progress over the
    WebSocket; and
  - a frontend sidebar tab (web/), a React app that wraps the human-in-the-loop
    confirm + approval gates the CLI engine exposes.

Boot contract: importing this pack must be cheap and must never break ComfyUI
boot. The route registration is guarded; the heavy engine/anthropic/torch imports
are all lazy (inside the route handlers / the worker thread), so a missing API
key or a transient engine issue degrades to an on-demand error, never a crash.
"""

# Serve web/ as the frontend (ComfyUI auto-loads top-level .js here as extensions).
WEB_DIRECTORY = "./web"

# Register the panel's backend routes on PromptServer. Guarded so a failure here
# is logged but never aborts ComfyUI's custom-node load.
try:
    from .nodeforge import server_routes  # noqa: F401  (import registers @routes)
except Exception as e:  # pragma: no cover
    print(f"[NodeForge] route registration failed (panel disabled): {e}")

# NodeForge adds no nodes to the graph -- it is a panel + routes.
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
