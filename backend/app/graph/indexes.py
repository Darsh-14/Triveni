"""Range indexes for one tenant graph. Idempotent: safe to run on every seed/startup."""
from falkordb import Graph

from backend.app.graph.schema import INDEXED_NODE_PROPS


def ensure_indexes(graph: Graph) -> list[str]:
    """Create `id` (and `name` where useful) range indexes; returns the ones created now."""
    created = []
    for label, props in INDEXED_NODE_PROPS.items():
        for prop in props:
            try:
                # Runs: CREATE INDEX FOR (n:<label>) ON (n.<prop>)  (labels/props come from the schema, not input)
                graph.create_node_range_index(label, prop)
                created.append(f"{label}.{prop}")
            except Exception as exc:  # FalkorDB raises if the index already exists
                if "already indexed" not in str(exc).lower():
                    raise
    return created
