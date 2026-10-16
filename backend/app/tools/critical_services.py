"""critical_services (Track 01): the most depended-on services by PageRank over DEPENDS_ON, with owners."""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

# algo.pageRank(label, relationshipType) takes one label and one type (docs.falkordb.com/algorithms/pagerank)
PAGERANK = """
CALL algo.pageRank('Service', 'DEPENDS_ON') YIELD node, score
RETURN node.id, node.name, node.tier, score
ORDER BY score DESC, node.id
LIMIT %d
"""

CONTEXT = """
MATCH (s:Service) WHERE s.id IN $ids
OPTIONAL MATCH (t:Team)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
OPTIONAL MATCH (d:Service)-[r:DEPENDS_ON]->(s) WHERE r.valid_to IS NULL
RETURN s.id, t.id, t.name, collect(DISTINCT d.id)
"""

# PageRank cannot filter on valid_to; dependencies are never ended in our data, and this checks that it stays true
ENDED_DEPS = "MATCH ()-[r:DEPENDS_ON]->() WHERE r.valid_to IS NOT NULL RETURN count(r)"


@tool(
    name="critical_services",
    description="The most critical services by PageRank over the dependency graph (a service ranks high when many "
                "services, especially critical ones, depend on it), with owning team and direct dependents. "
                "Unowned critical services are flagged.",
    input_schema={
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
        "additionalProperties": False,
    },
    tracks=("01",),
)
def critical_services(graph, limit: int = 5) -> ToolResult:
    limit = max(1, min(int(limit), 20))
    q = PAGERANK % limit
    ranked = [{"id": i, "name": n, "tier": t, "score": round(s, 5)} for i, n, t, s in ro(graph, q, {})]
    params = {"ids": [r["id"] for r in ranked]}
    ctx = {sid: (tid, tname, [d for d in deps if d]) for sid, tid, tname, deps in ro(graph, CONTEXT, params)}
    paths = []
    for r in ranked:
        tid, tname, deps = ctx.get(r["id"], (None, None, []))
        r.update(team=tid, team_name=tname, dependents=sorted(deps), unowned=tid is None)
        paths += [{"nodes": [d, r["id"]], "edges": [edge_ref("DEPENDS_ON", d, r["id"])]} for d in deps]
        if tid:
            paths.append({"nodes": [tid, r["id"]], "edges": [edge_ref("OWNS", tid, r["id"])]})
    ended = ro(graph, ENDED_DEPS, {})[0][0]
    unowned = [r["name"] for r in ranked if r["unowned"]]
    explanation = ("Most critical by PageRank on DEPENDS_ON: " + ", ".join(f"{r['name']} ({r['score']})" for r in ranked[:3])
                   + (f". Unowned: {', '.join(unowned)}." if unowned else "."))
    if ended:
        explanation += f" Warning: {ended} ended dependency edge(s) exist and PageRank still counts them."
    return ToolResult(data={"services": ranked, "algorithm": "algo.pageRank('Service','DEPENDS_ON')", "ended_dependencies": ended},
                      cypher=q.strip() + "\n\n" + CONTEXT.strip(), params=params, paths=paths, explanation=explanation)
