"""why_not (Track 03 + 01): absence proof. When the graph has no answer, say exactly which pattern was
checked, show that it matched nothing, and return what *is* nearby (history, owners, people who know it)."""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

CHECKS = {
    "on_call": "MATCH (p:Person)-[r:ON_CALL_FOR]->(s:Service {name: $service}) WHERE r.valid_to IS NULL RETURN p.id",
    "owner": "MATCH (t:Team)-[r:OWNS]->(s:Service {name: $service}) WHERE r.valid_to IS NULL RETURN t.id",
}
DEPENDS = ("MATCH p=(a:Service {name: $from})-[:DEPENDS_ON*1..%d]->(b:Service {name: $to}) "
           "WHERE all(r IN relationships(p) WHERE r.valid_to IS NULL) RETURN [n IN nodes(p) | n.id] LIMIT 1")

EXISTS = "MATCH (s:Service {name: $service}) RETURN s.id"
HISTORY = """
MATCH (x)-[r:%s]->(s:Service {name: $service}) WHERE r.valid_to IS NOT NULL
RETURN x.id, r.valid_from, r.valid_to, r.source_doc, r.ended_by
"""
OWNER_TEAM = """
MATCH (t:Team)-[r:OWNS]->(s:Service {name: $service}) WHERE r.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[m:MEMBER_OF]->(t) WHERE m.valid_to IS NULL
OPTIONAL MATCH (p)-[k:KNOWS]->(s)
RETURN t.id, r.source_doc, p.id, p.name, coalesce(k.weight, 0) AS w ORDER BY w DESC, p.id
"""
KNOWERS = "MATCH (p:Person)-[k:KNOWS]->(s:Service {name: $service}) RETURN p.id, p.name, k.weight ORDER BY k.weight DESC, p.id LIMIT 3"

# Nobody on call: who is on call right now for a service within 2 dependency hops (either direction), ranked by how
# well they know this one (derived KNOWS), then by distance - the nearest awake person who can help
NEARBY = """
MATCH (s:Service {name: $service})
MATCH near=(s)-[:DEPENDS_ON*1..2]-(n:Service)
WHERE n <> s AND all(r IN relationships(near) WHERE r.valid_to IS NULL)
WITH s, n, min(length(near)) AS hops
MATCH (p:Person)-[c:ON_CALL_FOR]->(n) WHERE c.valid_to IS NULL
OPTIONAL MATCH (p)-[k:KNOWS]->(s)
RETURN p.id, p.name, n.id, n.name, hops, coalesce(k.weight, 0) AS weight
ORDER BY weight DESC, hops, p.id LIMIT 3
"""
ALLOWED_DEPTHS = {1, 2, 3, 4}


@tool(
    name="why_not",
    description="Prove an absence. kind=on_call or owner: is there a current on-call engineer / owning team for `service`? "
                "kind=depends: does `service` depend on `other` within `depth` hops? Returns the exact pattern checked, "
                "whether it matched, and nearby context (past edges and what ended them, owning team, who knows the service).",
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["on_call", "owner", "depends"]},
            "service": {"type": "string"},
            "other": {"type": "string", "description": "kind=depends only: the target service"},
            "depth": {"type": "integer", "enum": [1, 2, 3, 4], "default": 4},
        },
        "required": ["kind", "service"],
        "additionalProperties": False,
    },
    tracks=("03", "01"),
    entities={"service": (("Service",), "name"), "other": (("Service",), "name")},
)
def why_not(graph, kind: str, service: str, other: str | None = None, depth: int = 4) -> ToolResult:
    service = service.removeprefix("svc:")
    params = {"service": service}
    if not ro(graph, EXISTS, params):
        return ToolResult(data={"kind": kind, "service": service, "service_exists": False}, cypher=EXISTS, params=params,
                          explanation=f"There is no service named {service}, so nothing else was checked.",
                          outcome="unknown_entity")

    if kind == "depends":
        if not other or depth not in ALLOWED_DEPTHS:
            raise ValueError("kind=depends needs `other` and depth in 1..4")
        check = DEPENDS % depth  # depth is validated against ALLOWED_DEPTHS; names are parameters
        params = {"from": service, "to": other.removeprefix("svc:")}
        found = ro(graph, check, params)
        reverse = ro(graph, check, {"from": params["to"], "to": service})
        params["other"] = params["to"]
        path = found[0][0] if found else []
        data = {"kind": kind, "service": f"svc:{service}", "other": f"svc:{params['other']}", "exists": bool(found),
                "path": path, "reverse_path": reverse[0][0] if reverse else []}
        paths = [{"nodes": path, "edges": [edge_ref("DEPENDS_ON", a, b) for a, b in zip(path, path[1:])]}] if path else []
        explanation = (f"{service} depends on {params['other']} via {' -> '.join(path)}." if found else
                       f"No DEPENDS_ON path of length 1..{depth} from {service} to {params['other']}"
                       + (f"; the reverse exists ({' -> '.join(data['reverse_path'])})." if reverse else "."))
        return ToolResult(data=data, cypher=check, params=params, paths=paths, explanation=explanation,
                          outcome="answered" if found else "not_in_graph")

    check = CHECKS[kind]
    found = [r[0] for r in ro(graph, check, params)]
    rel = "ON_CALL_FOR" if kind == "on_call" else "OWNS"
    history_q = HISTORY % rel
    history = [{"id": x, "valid_from": vf, "valid_to": vt, "source": src, "ended_by": eb}
               for x, vf, vt, src, eb in ro(graph, history_q, params)]
    owner_rows = ro(graph, OWNER_TEAM, params)
    owner = owner_rows[0][0] if owner_rows else None
    contacts = [{"id": pid, "name": name, "knows_weight": w} for _, _, pid, name, w in owner_rows if pid][:3]
    knowers = [{"id": pid, "name": name, "weight": w} for pid, name, w in ro(graph, KNOWERS, params)]

    svc_id = f"svc:{service}"
    paths = [{"nodes": [x, svc_id], "edges": [edge_ref(rel, x, svc_id)]} for x in found]
    paths += [{"nodes": [h["id"], svc_id], "edges": [edge_ref(rel, h["id"], svc_id)], "superseded": True} for h in history]
    if owner:
        paths.append({"nodes": [owner, svc_id], "edges": [edge_ref("OWNS", owner, svc_id)]})
        paths += [{"nodes": [c["id"], owner], "edges": [edge_ref("MEMBER_OF", c["id"], owner)]} for c in contacts]
    sources = sorted({h["source"] for h in history if h["source"]} | {h["ended_by"] for h in history if h["ended_by"]}
                     | ({owner_rows[0][1]} if owner_rows and owner_rows[0][1] else set()))
    nearby = []
    if kind == "on_call" and not found:  # nobody on call: the nearest people who are, ranked by what they know
        nearby = [{"id": pid, "name": name, "on_call_for": nid, "on_call_for_name": nname, "hops": hops, "knows_weight": w}
                  for pid, name, nid, nname, hops, w in ro(graph, NEARBY, params)]
        for n in nearby:
            paths.append({"nodes": [n["id"], n["on_call_for"]], "edges": [edge_ref("ON_CALL_FOR", n["id"], n["on_call_for"])]})
    data = {"kind": kind, "service": svc_id, "exists": bool(found), "found": found, "checked": check,
            "history": history, "owner_team": owner, "suggested_contacts": contacts, "people_who_know_it": knowers,
            "nearby_on_call": nearby}
    what = "on-call engineer" if kind == "on_call" else "owning team"
    explanation = (f"{service} has a current {what}: {', '.join(found)}." if found else
                   f"No current {what} for {service}: the pattern matched 0 edges"
                   + (f" ({len(history)} past edge(s) ended)" if history else " and none ever existed")
                   + (f". Owner {owner}; best contacts {', '.join(c['name'] for c in contacts)}." if owner and contacts else ".")
                   + (" Nearest on-call now: " + "; ".join(
                       f"{n['name']} (on call for {n['on_call_for_name']}, {n['hops']} hop(s) away"
                       + (", knows it" if n["knows_weight"] else "") + ")" for n in nearby) + "." if nearby else ""))
    return ToolResult(data=data, cypher="\n\n".join([check, history_q.strip(), OWNER_TEAM.strip(), KNOWERS]
                                                    + ([NEARBY.strip()] if nearby else [])),
                      params=params, paths=paths, sources=sources, explanation=explanation,
                      outcome="answered" if found else "not_in_graph")
