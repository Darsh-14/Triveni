"""owner_of (Track 03): who owns a service and who is on call, with sources, optionally with history."""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

CURRENT = """
MATCH (s:Service {name: $service})
OPTIONAL MATCH (t:Team)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
WITH s, collect({id: t.id, name: t.name, source: o.source_doc, since: o.valid_from}) AS owners
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(s) WHERE c.valid_to IS NULL
RETURN s.id, owners, collect({id: p.id, name: p.name, source: c.source_doc, since: c.valid_from}) AS oncall
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
    cypher = CURRENT.strip()

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
        explanation=f"{service} is currently owned by {owner_txt}; on call: {oncall_txt} (current edges only, valid_to absent).",
    )
