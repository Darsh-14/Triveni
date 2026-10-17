"""shortest_path (Track 01): how two things are connected: a service dependency chain, or any fact path
(person -> incident -> service ...). Bounded variable-length matches ordered by length: FalkorDB's shortestPath()
cannot filter on properties, and a dependency that ended (valid_to set) must not count as a current chain."""
from backend.app.graph.resolve import FACT_LABELS
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

# Fact edges only (no MENTIONS: registry documents mention everything and would make every path trivial).
FACT_TYPES = "MEMBER_OF|OWNS|ON_CALL_FOR|DEPENDS_ON|AUTHORED|DEPLOYED_TO|AFFECTED|CAUSED_BY|RESOLVED|MADE|GOVERNS|SUPERSEDES"
MODES = {
    # directed: follows what `from` needs, current DEPENDS_ON edges only (~0.03 s on the demo graph)
    "dependency": "MATCH p=(a:Service {id: $from})-[:DEPENDS_ON*1..8]->(b:Service {id: $to}) "
                  "WHERE all(r IN relationships(p) WHERE r.valid_to IS NULL) "
                  "WITH p ORDER BY length(p) LIMIT 1 "
                  "RETURN [n IN nodes(p) | n.id], [r IN relationships(p) | type(r)], "
                  "[r IN relationships(p) | startNode(r).id], [r IN relationships(p) | r.valid_to]",
    # undirected: FalkorDB's shortestPath() does not support undirected patterns, so this is a bounded
    # variable-length match ordered by length (fine at this graph size; the hop cap keeps it cheap).
    # Paths over current facts win; a path through ended edges is returned only when nothing current connects them.
    "any": f"MATCH p=(a {{id: $from}})-[:{FACT_TYPES}*1..4]-(b {{id: $to}}) "
           "WITH p, size([r IN relationships(p) WHERE r.valid_to IS NOT NULL]) AS ended "
           "ORDER BY ended, length(p) LIMIT 1 "
           "RETURN [n IN nodes(p) | n.id], [r IN relationships(p) | type(r)], "
           "[r IN relationships(p) | startNode(r).id], [r IN relationships(p) | r.valid_to]",
}


def _node_id(x: str) -> str:
    return x if ":" in x else f"svc:{x}"  # bare names are services


@tool(
    name="shortest_path",
    description="Shortest connection between two graph entities. mode=dependency: directed DEPENDS_ON chain from service "
                "`from` to service `to`. mode=any: any fact relationship in either direction (use ids like per:priya-nair, "
                "svc:billing-batch, inc:0042). Returns the node and edge sequence.",
    input_schema={
        "type": "object",
        "properties": {
            "from": {"type": "string", "description": "start entity id (or service name)"},
            "to": {"type": "string", "description": "end entity id (or service name)"},
            "mode": {"type": "string", "enum": ["dependency", "any"], "default": "dependency"},
        },
        "required": ["from", "to"],
        "additionalProperties": False,
    },
    tracks=("01",),
    entities={"from": (lambda a: ("Service",) if a.get("mode", "dependency") == "dependency" else FACT_LABELS, "id"),
              "to": (lambda a: ("Service",) if a.get("mode", "dependency") == "dependency" else FACT_LABELS, "id")},
)
def shortest_path(graph, mode: str = "dependency", **ends) -> ToolResult:
    if mode not in MODES:
        raise ValueError("mode must be dependency or any")
    params = {"from": _node_id(ends["from"]), "to": _node_id(ends["to"])}
    q = MODES[mode]
    rows = ro(graph, q, params)
    nodes, types, starts, ended = rows[0] if rows and rows[0][0] else ([], [], [], [])
    edges = [edge_ref(t, s, b if s == a else a) for t, s, a, b in zip(types, starts, nodes, nodes[1:])]
    stale = [e for e, vt in zip(edges, ended) if vt is not None]
    data = {"from": params["from"], "to": params["to"], "mode": mode, "found": bool(nodes),
            "nodes": nodes, "edges": edges, "hops": len(edges), "includes_ended_edges": stale}
    explanation = (f"{params['from']} reaches {params['to']} in {len(edges)} hop(s): {' -> '.join(nodes)}."
                   if nodes else f"No {mode} path from {params['from']} to {params['to']} within {8 if mode == 'dependency' else 4} hops.")
    if stale:
        explanation += f" Note: {len(stale)} edge(s) on this path are historical (valid_to set)."
    return ToolResult(data=data, cypher=q, params=params,
                      paths=[{"nodes": nodes, "edges": edges}] if nodes else [], explanation=explanation)
