"""who_knows (Track 03): people ranked by expertise on a service, each with the evidence behind it."""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

RANK = """
MATCH (p:Person)-[k:KNOWS]->(s:Service {name: $service})
OPTIONAL MATCH (p)-[m:MEMBER_OF]->(t:Team) WHERE m.valid_to IS NULL
RETURN p.id, p.name, t.name, k.weight
ORDER BY k.weight DESC, p.id
LIMIT %d
"""

# One row per piece of evidence (person -> via node -> service). The via node is returned, so every path counts.
EVIDENCE = """
MATCH (p:Person)-[r:RESOLVED]->(x:Incident)-[:AFFECTED]->(s:Service {name: $service}) WHERE p.id IN $people
RETURN p.id AS person, 'RESOLVED' AS rel, x.id AS via, x.title AS what, r.source_doc AS source, s.id AS service
UNION ALL
MATCH (p:Person)-[r:AUTHORED]->(x:Deployment)-[:DEPLOYED_TO]->(s:Service {name: $service}) WHERE p.id IN $people
RETURN p.id AS person, 'AUTHORED' AS rel, x.id AS via, x.version AS what, r.source_doc AS source, s.id AS service
UNION ALL
MATCH (p:Person)-[r:MADE]->(x:Decision)-[:GOVERNS]->(s:Service {name: $service}) WHERE p.id IN $people
RETURN p.id AS person, 'MADE' AS rel, x.id AS via, x.title AS what, r.source_doc AS source, s.id AS service
UNION ALL
MATCH (p:Person)-[:WROTE]->(x:Document)-[:MENTIONS]->(s:Service {name: $service}) WHERE p.id IN $people
RETURN p.id AS person, 'WROTE' AS rel, x.id AS via, x.title AS what, x.id AS source, s.id AS service
UNION ALL
MATCH (p:Person)-[r:ON_CALL_FOR]->(s:Service {name: $service}) WHERE p.id IN $people AND r.valid_to IS NULL
RETURN p.id AS person, 'ON_CALL_FOR' AS rel, s.id AS via, s.name AS what, r.source_doc AS source, s.id AS service
"""
SECOND_HOP = {"RESOLVED": "AFFECTED", "AUTHORED": "DEPLOYED_TO", "MADE": "GOVERNS", "WROTE": "MENTIONS"}


@tool(
    name="who_knows",
    description="People who know a service best, ranked by evidence weight (resolved incidents x3, deployments x2, "
                "decisions x2, documents written x1, current on-call x1), with each piece of evidence.",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "service name"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        },
        "required": ["service"],
        "additionalProperties": False,
    },
    tracks=("03",),
    entities={"service": (("Service",), "name")},
)
def who_knows(graph, service: str, limit: int = 5) -> ToolResult:
    service = service.removeprefix("svc:")
    limit = max(1, min(int(limit), 20))  # validated integer; LIMIT is interpolated, values stay parameters
    rank_q = RANK % limit
    people = [{"id": pid, "name": name, "team": team, "weight": w, "evidence": []}
              for pid, name, team, w in ro(graph, rank_q, {"service": service})]
    by_id = {p["id"]: p for p in people}
    params = {"service": service, "people": list(by_id)}
    paths, sources = [], set()
    for person, rel, via, what, source, svc in (ro(graph, EVIDENCE, params) if people else []):
        by_id[person]["evidence"].append({"rel": rel, "via": via, "what": what, "source": source})
        if source:
            sources.add(source)
        if rel == "ON_CALL_FOR":
            paths.append({"nodes": [person, svc], "edges": [edge_ref(rel, person, svc)]})
        else:
            paths.append({"nodes": [person, via, svc],
                          "edges": [edge_ref(rel, person, via), edge_ref(SECOND_HOP[rel], via, svc)]})
    top = ", ".join(f"{p['name']} ({p['weight']})" for p in people[:3]) or "nobody"
    return ToolResult(
        data={"service": f"svc:{service}", "people": people}, cypher=rank_q.strip() + "\n\n" + EVIDENCE.strip(),
        params=params, paths=paths, sources=sorted(sources),
        explanation=f"Ranked by summed evidence on {service} (derived KNOWS edges, rebuilt from current facts): {top}.",
    )
