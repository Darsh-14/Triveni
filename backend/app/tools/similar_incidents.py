"""similar_incidents (Track 03): past incidents on a service or its direct dependency neighbours,
with who resolved them, what caused them and the postmortem to read."""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

CANDIDATES = """
MATCH (i:Incident)-[:AFFECTED]->(s:Service {name: $service})
RETURN i.id AS id, i.title AS title, i.ts_open AS ts, s.id AS via, 0 AS hops
UNION
MATCH (i:Incident)-[:AFFECTED]->(t:Service)-[d:DEPENDS_ON]-(s:Service {name: $service}) WHERE d.valid_to IS NULL
RETURN i.id AS id, i.title AS title, i.ts_open AS ts, t.id AS via, 1 AS hops
"""

DETAILS = """
MATCH (i:Incident) WHERE i.id IN $ids
OPTIONAL MATCH (p:Person)-[:RESOLVED]->(i)
OPTIONAL MATCH (doc:Document {kind: 'postmortem'})-[:EVIDENCE_FOR]->(i)
OPTIONAL MATCH (i)-[:CAUSED_BY]->(dep:Deployment)
RETURN i.id, i.summary, i.ts_close, collect(DISTINCT p.id), collect(DISTINCT doc.id), collect(DISTINCT dep.id)
"""

SERVICE_OF = "MATCH (i:Incident {id: $incident})-[:AFFECTED]->(s:Service) RETURN s.name"


@tool(
    name="similar_incidents",
    description="Past incidents similar to a service's current trouble: incidents on the same service first, then on "
                "services it depends on or that depend on it. Includes resolvers, cause deployment and postmortem. "
                "Give `service`, or `incident` to find ones similar to a known incident.",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "service name"},
            "incident": {"type": "string", "description": "incident id, e.g. inc:0057 (alternative to service)"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        },
        "additionalProperties": False,
    },
    tracks=("03", "02"),
    entities={"service": (("Service",), "name"), "incident": (("Incident",), "id")},
)
def similar_incidents(graph, service: str | None = None, incident: str | None = None, limit: int = 5) -> ToolResult:
    cypher = CANDIDATES.strip()
    if not service and incident:
        rows = ro(graph, SERVICE_OF, {"incident": incident})
        service = rows[0][0] if rows else None
        cypher = SERVICE_OF + "\n\n" + cypher
    if not service:
        return ToolResult(data={"found": False}, cypher=cypher, params={"incident": incident},
                          explanation="Need a service name or a known incident id.")
    service = service.removeprefix("svc:")
    params = {"service": service}
    seen, candidates = set(), []
    for iid, title, ts, via, hops in sorted(ro(graph, CANDIDATES, params), key=lambda r: (r[4], r[2] and -_ts(r[2]))):
        if iid in seen or iid == incident:
            continue
        seen.add(iid)
        candidates.append({"id": iid, "title": title, "ts_open": ts, "via": via, "hops": hops})
    candidates = candidates[: max(1, min(int(limit), 20))]

    detail_params = {"ids": [c["id"] for c in candidates]}
    details = {iid: (summary, closed, [p for p in ps if p], [d for d in docs if d], [x for x in deps if x])
               for iid, summary, closed, ps, docs, deps in (ro(graph, DETAILS, detail_params) if candidates else [])}
    paths, sources = [], set()
    for c in candidates:
        summary, closed, resolvers, docs, causes = details.get(c["id"], ("", None, [], [], []))
        c.update(summary=summary, ts_close=closed, resolved_by=resolvers, postmortems=docs, caused_by=causes)
        sources |= set(docs)
        paths.append({"nodes": [c["id"], c["via"]], "edges": [edge_ref("AFFECTED", c["id"], c["via"])]})
        paths += [{"nodes": [p, c["id"]], "edges": [edge_ref("RESOLVED", p, c["id"])]} for p in resolvers]
        paths += [{"nodes": [c["id"], d], "edges": [edge_ref("CAUSED_BY", c["id"], d)]} for d in causes]
    same = sum(1 for c in candidates if c["hops"] == 0)
    return ToolResult(
        data={"service": f"svc:{service}", "incidents": candidates}, cypher=cypher + "\n\n" + DETAILS.strip(),
        params=params | detail_params, paths=paths, sources=sorted(sources),
        explanation=f"{same} incident(s) on {service} itself and {len(candidates) - same} on its direct dependency neighbours, "
                    f"newest first within each group.",
    )


def _ts(iso: str) -> int:
    return int(iso[:4] + iso[5:7] + iso[8:10] + iso[11:13] + iso[14:16] + iso[17:19])
