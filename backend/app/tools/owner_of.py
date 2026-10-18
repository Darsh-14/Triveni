"""owner_of (Track 03): who owns a service and who is on call, with sources, optionally with history.

Beyond the direct edges it answers the next two questions an on-call engineer asks, both by traversal:
  upstream: who owns and is on call for what this service needs (DEPENDS_ON, 1-2 hops, current edges) - who else to loop in
  escalation: the owning team's members ranked by derived expertise on this service (KNOWS, built from deploys,
              resolved incidents, decisions and docs) - who to call if the on-call engineer does not answer
"""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

CURRENT = """
MATCH (s:Service {name: $service})
OPTIONAL MATCH (t:Team)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
WITH s, collect({id: t.id, name: t.name, source: o.source_doc, since: o.valid_from}) AS owners
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(s) WHERE c.valid_to IS NULL
RETURN s.id, owners, collect({id: p.id, name: p.name, source: c.source_doc, since: c.valid_from}) AS oncall
"""

UPSTREAM = """
MATCH up=(s:Service {name: $service})-[:DEPENDS_ON*1..2]->(u:Service)
WHERE all(r IN relationships(up) WHERE r.valid_to IS NULL)
WITH u, up ORDER BY length(up)
WITH u, collect([n IN nodes(up) | n.id])[0] AS path
OPTIONAL MATCH (t:Team)-[o:OWNS]->(u) WHERE o.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(u) WHERE c.valid_to IS NULL
RETURN u.id, u.name, path, t.id, t.name, p.id, p.name
ORDER BY size(path), u.id
"""

ESCALATION = """
MATCH (t:Team)-[o:OWNS]->(s:Service {name: $service}) WHERE o.valid_to IS NULL
MATCH (p:Person)-[m:MEMBER_OF]->(t) WHERE m.valid_to IS NULL
OPTIONAL MATCH (p)-[k:KNOWS]->(s)
WITH p, coalesce(k.weight, 0) AS weight WHERE weight > 0
RETURN p.id, p.name, weight ORDER BY weight DESC, p.id LIMIT 3
"""

HISTORY = """
MATCH (x)-[r:OWNS|ON_CALL_FOR]->(s:Service {name: $service})
RETURN type(r), x.id, x.name, r.valid_from, r.valid_to, r.source_doc
ORDER BY r.valid_from
"""


@tool(
    name="owner_of",
    description="Current owning team and on-call engineer for a service, each with the source document of the fact. "
                "Set include_history to also list past owners/on-call (facts that were superseded, with valid_from/valid_to).",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "service name, e.g. payments-api"},
            "include_history": {"type": "boolean", "default": False},
        },
        "required": ["service"],
        "additionalProperties": False,
    },
    tracks=("03",),
    entities={"service": (("Service",), "name")},
)
def owner_of(graph, service: str, include_history: bool = False) -> ToolResult:
    service = service.removeprefix("svc:")
    params = {"service": service}
    rows = ro(graph, CURRENT, params)
    if not rows:
        return ToolResult(data={"found": False, "service": service}, cypher=CURRENT.strip(), params=params,
                          explanation=f"No service named {service} exists in this tenant's graph.")
    svc_id, owners, oncall = rows[0]
    owners = [o for o in owners if o["id"]]
    oncall = [p for p in oncall if p["id"]]
    paths = [{"nodes": [o["id"], svc_id], "edges": [edge_ref("OWNS", o["id"], svc_id)]} for o in owners]
    paths += [{"nodes": [p["id"], svc_id], "edges": [edge_ref("ON_CALL_FOR", p["id"], svc_id)]} for p in oncall]
    sources = {x["source"] for x in owners + oncall if x["source"]}
    data = {"found": True, "service": svc_id, "owners": owners, "on_call": oncall}
    cypher = CURRENT.strip() + "\n\n" + UPSTREAM.strip() + "\n\n" + ESCALATION.strip()

    upstream = [{"id": uid, "name": uname, "hops": len(path) - 1, "path": path, "team": tid, "team_name": tname,
                 "on_call": pid, "on_call_name": pname}
                for uid, uname, path, tid, tname, pid, pname in ro(graph, UPSTREAM, params)]
    escalation = [{"id": pid, "name": pname, "knows_weight": w} for pid, pname, w in ro(graph, ESCALATION, params)]
    data["upstream"], data["escalation"] = upstream, escalation
    for u in upstream:
        paths.append({"nodes": u["path"], "edges": [edge_ref("DEPENDS_ON", a, b) for a, b in zip(u["path"], u["path"][1:])]})
        if u["on_call"]:
            paths.append({"nodes": [u["on_call"], u["id"]], "edges": [edge_ref("ON_CALL_FOR", u["on_call"], u["id"])]})
    for e in escalation:
        paths.append({"nodes": [e["id"], svc_id], "edges": [edge_ref("KNOWS", e["id"], svc_id)]})

    if include_history:
        history = [
            {"relation": rel, "id": xid, "name": name, "valid_from": vf, "valid_to": vt, "source": src}
            for rel, xid, name, vf, vt, src in ro(graph, HISTORY, params)
        ]
        data["history"] = history
        sources |= {h["source"] for h in history if h["source"]}
        cypher += "\n\n" + HISTORY.strip()

    owner_txt = ", ".join(o["name"] for o in owners) or "no team"
    oncall_txt = ", ".join(p["name"] for p in oncall) or "nobody"
    return ToolResult(
        data=data, cypher=cypher, params=params, paths=paths, sources=sorted(sources),
        explanation=f"{service} is currently owned by {owner_txt}; on call: {oncall_txt} (current edges only, valid_to absent)."
                    + (f" It needs {len(upstream)} service(s) within 2 hops; loop in: "
                       + "; ".join(f"{u['name']} ({u['team_name'] or 'no owner'}, on call {u['on_call_name'] or 'nobody'})"
                                   for u in upstream[:4]) + "." if upstream else "")
                    + (f" Escalation by expertise: {', '.join(e['name'] for e in escalation)}." if escalation else ""),
    )
