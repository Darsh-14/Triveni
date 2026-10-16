"""recall (Track 02): past episodes that share graph entities with the current problem, with their lessons and
procedures (and how often each procedure worked)."""
from backend.app.memory.recall import EXPAND, RECALL, recall as recall_episodes
from backend.app.tools.base import ToolResult, edge_ref, tool


@tool(
    name="recall",
    description="Memory: find past episodes (earlier investigations by any agent) that involved the same services, "
                "incidents or people, through the graph, not text search. Returns what was learned and which "
                "procedures were used, with success/fail counts. Call this early when investigating a problem.",
    input_schema={
        "type": "object",
        "properties": {
            "entities": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                         "description": "entity ids, e.g. [\"svc:payments-api\", \"inc:0042\"]; bare names are treated as services"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
        },
        "required": ["entities"],
        "additionalProperties": False,
    },
    tracks=("02",),
)
def recall(graph, entities: list[str], limit: int = 5) -> ToolResult:
    ids = [e if ":" in e else f"svc:{e}" for e in entities]
    found = recall_episodes(graph, ids, max(1, min(int(limit), 10)))
    paths = []
    for ep in found["episodes"]:
        paths += [{"nodes": [ep["id"], x], "edges": [edge_ref("INVOLVED", ep["id"], x)]} for x in ep["shared"]]
        paths += [{"nodes": [ep["id"], p["id"]], "edges": [edge_ref("USED", ep["id"], p["id"])]} for p in ep["procedures"]]
        paths += [{"nodes": [ep["id"], lesson["id"]], "edges": [edge_ref("LEARNED", ep["id"], lesson["id"])]} for lesson in ep["lessons"]]
    best = found["episodes"][0] if found["episodes"] else None
    faded = [lesson["id"] for ep in found["episodes"] for lesson in ep["lessons"] if lesson["faded"]]
    explanation = (f"{len(found['episodes'])} past episode(s) share entities with {', '.join(ids)}. "
                   + (f"Closest: {best['id']} ({best['outcome']}, shared {', '.join(best['shared'])})"
                      + (f"; procedure '{best['procedures'][0]['name']}' worked {best['procedures'][0]['success_count']}x, "
                         f"failed {best['procedures'][0]['fail_count']}x" if best["procedures"] else "") + "."
                      if best else "Nothing in memory yet.")
                   + (f" Lessons decay with a {found['half_life_days']:g}-day half-life"
                      + (f"; faded: {', '.join(faded)}." if faded else ".") if found["episodes"] else ""))
    return ToolResult(data=found, cypher=EXPAND.strip() + "\n\n" + RECALL.strip(),
                      params={"ids": found["expanded"], "limit": limit}, paths=paths, explanation=explanation)
