from .nodes.probe_nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

print(f"[NodeProbe] loaded {len(NODE_CLASS_MAPPINGS)} probe nodes: {', '.join(NODE_CLASS_MAPPINGS)}")
