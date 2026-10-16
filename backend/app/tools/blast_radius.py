"""blast_radius (Track 01): which services break if this one fails (multi-hop DEPENDS_ON), and who owns them."""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

ALLOWED_DEPTHS = {1, 2, 3, 4}

# (A)-[:DEPENDS_ON]->(B) means A needs B, so the blast radius of B is everything that reaches B.
DEPENDENTS = """
MATCH p=(d:Service)-[:DEPENDS_ON*1..%d]->(s:Service {name: $service})
WHERE all(r IN relationships(p) WHERE r.valid_to IS NULL)
RETURN d.id, d.name, d.tier, length(p) AS hops, [n IN nodes(p) | n.id] AS path
ORDER BY hops, d.id
"""

OWNERS = """
MATCH (t:Team)-[o:OWNS]->(s:Service) WHERE s.id IN $ids AND o.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(s) WHERE c.valid_to IS NULL
RETURN s.id, t.id, t.name, p.id, p.name, o.source_doc, c.source_doc
"""


@tool(
    name="blast_radius",
    description="Services that depend on `service` directly or transitively (up to `depth` hops), i.e. what breaks if it "
                "fails, with hop distance, tier, owning team and on-call for each, including the failing service itself.",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "the failing service, e.g. payments-api"},
            "depth": {"type": "integer", "enum": [1, 2, 3, 4], "default": 3},
        },
        "required": ["service"],
        "additionalProperties": False,
    },
    tracks=("01",),
)
def blast_radius(graph, service: str, depth: int = 3) -> ToolResult:
    if depth not in ALLOWED_DEPTHS:
        raise ValueError("depth must be 1..4")
    service = service.removeprefix("svc:")
    params = {"service": service}
    q = DEPENDENTS % depth  # validated integer; the service name stays a parameter
    affected, paths = {}, []
    for dep_id, name, tier, hops, path in ro(graph, q, params):
        affected.setdefault(dep_id, {"id": dep_id, "name": name, "tier": tier, "hops": hops, "path": path})
        paths.append({"nodes": path, "edges": [edge_ref("DEPENDS_ON", a, b) for a, b in zip(path, path[1:])]})

    ids = [f"svc:{service}", *affected]
    owners, sources = {}, set()
    for sid, tid, tname, pid, pname, osrc, csrc in ro(graph, OWNERS, {"ids": ids}):
        owners[sid] = {"team": tid, "team_name": tname, "on_call": pid, "on_call_name": pname}
        sources |= {x for x in (osrc, csrc) if x}
    for sid in affected:
        affected[sid].update(owners.get(sid, {"team": None, "on_call": None}))
    failing = {"id": f"svc:{service}", **owners.get(f"svc:{service}", {"team": None, "on_call": None})}
    # who to page: the failing service's on-call and owner, plus the owning team of each affected service
    for sid, o in owners.items():
        if o["team"]:
            paths.append({"nodes": [o["team"], sid], "edges": [edge_ref("OWNS", o["team"], sid)]})
    if failing.get("on_call"):
        paths.append({"nodes": [failing["on_call"], failing["id"]], "edges": [edge_ref("ON_CALL_FOR", failing["on_call"], failing["id"])]})
    tier1 = [a["name"] for a in affected.values() if a["tier"] == 1]
    page = (f" Page {failing['on_call_name']} (on call for {service}, team {failing['team_name']})."
            if failing.get("on_call") else f" Nobody is on call for {service}.")
    return ToolResult(
        data={"service": failing, "depth": depth, "affected": list(affected.values())},
        cypher=q.strip() + "\n\n" + OWNERS.strip(), params=params | {"ids": ids}, paths=paths, sources=sorted(sources),
        explanation=f"{len(affected)} service(s) depend on {service} within {depth} hops"
                    + (f" ({len(tier1)} tier-1: {', '.join(tier1)})" if tier1 else "") + "; only current DEPENDS_ON edges." + page,
    )
