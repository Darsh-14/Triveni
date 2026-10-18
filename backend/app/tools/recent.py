"""recent (Track 01 / 03): what changed most recently, and who did or approved it.

Answers questions that name no entity: "who approved the most recent change?", "what was the last deploy?", "latest
SEV1?", "what decisions were made recently?", "what is waiting for approval?". Each kind is one fixed, parameterized
query ordered by its own timestamp; an optional service narrows it. A "change" is a deployment or an approved action;
the graph records approvals only on actions, and the explanation says so instead of inventing an approver.
"""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

KINDS = ("deployments", "incidents", "decisions", "actions")

# the service filter is chosen by code (never built from input); the service name itself stays a parameter
ANY, ONE = "", " {name: $service}"

QUERIES = {
    "deployments": """
MATCH (p:Person)-[a:AUTHORED]->(d:Deployment)-[:DEPLOYED_TO]->(s:Service%s)
OPTIONAL MATCH (i:Incident)-[:CAUSED_BY]->(d)
RETURN d.id, d.version, d.ts, d.status, s.id, s.name, p.id, p.name, collect(DISTINCT i.id), a.source_doc
ORDER BY d.ts DESC LIMIT $limit""",
    "incidents": """
MATCH (i:Incident)-[f:AFFECTED]->(s:Service%s)
OPTIONAL MATCH (p:Person)-[:RESOLVED]->(i)
OPTIONAL MATCH (i)-[:CAUSED_BY]->(d:Deployment)
RETURN i.id, i.title, i.severity, i.ts_open, i.ts_close, s.id, s.name, collect(DISTINCT p.name), collect(DISTINCT d.id), f.source_doc
ORDER BY i.ts_open DESC LIMIT $limit""",
    "decisions": """
MATCH (m:Person)-[:MADE]->(d:Decision)-[g:GOVERNS]->(s:Service%s)
OPTIONAL MATCH (n:Decision)-[:SUPERSEDES]->(d)
RETURN d.id, d.title, d.ts, d.status, collect(DISTINCT s.name), m.id, m.name, collect(DISTINCT n.id), g.source_doc
ORDER BY d.ts DESC LIMIT $limit""",
    "actions": """
MATCH (a:Action)-[:TARGETS]->(s:Service%s)
OPTIONAL MATCH (p:Person)-[:APPROVED]->(a)
OPTIONAL MATCH (a)-[:BLOCKED_BY]->(d:Decision)
RETURN a.id, a.kind, a.status, a.ts, a.decided_ts, a.proposed_by, s.id, s.name, p.id, p.name, collect(DISTINCT d.id)
ORDER BY coalesce(a.decided_ts, a.ts) DESC LIMIT $limit""",
}


@tool(
    name="recent",
    description="The most recent events of one kind, newest first, with who did them: deployments (author, status, "
                "incidents they caused), incidents (severity, resolvers, cause), decisions (who made them, superseded?), "
                "actions (status, who approved, blocking decision). Optional service filter. Use for 'what changed "
                "recently', 'who approved the last change', 'latest deploy / incident / decision', 'what awaits approval'.",
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "service": {"type": "string", "description": "optional service name, e.g. payments-api"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        },
        "required": ["kind"],
        "additionalProperties": False,
    },
    tracks=("01", "03"),
    entities={"service": (("Service",), "name")},
)
def recent(graph, kind: str, service: str | None = None, limit: int = 5) -> ToolResult:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}")
    q = QUERIES[kind] % (ONE if service else ANY)
    params = {"limit": max(1, min(int(limit), 20)), **({"service": service} if service else {})}
    items, paths, sources = [], [], set()
    for row in ro(graph, q, params):
        if kind == "deployments":
            did, ver, ts, status, sid, sname, pid, pname, caused, src = row
            items.append({"id": did, "version": ver, "ts": ts, "status": status, "service": sid, "author": pid,
                          "author_name": pname, "caused": [c for c in caused if c]})
            paths.append({"nodes": [pid, did, sid], "edges": [edge_ref("AUTHORED", pid, did), edge_ref("DEPLOYED_TO", did, sid)]})
            line = f"{sname} {ver} by {pname} ({ts[:10]}, {status}" + (f"; caused {', '.join(items[-1]['caused'])}" if items[-1]["caused"] else "") + ")"
        elif kind == "incidents":
            iid, title, sev, opened, closed, sid, sname, resolvers, causes, src = row
            items.append({"id": iid, "title": title, "severity": sev, "ts_open": opened, "ts_close": closed, "service": sid,
                          "resolved_by": [r for r in resolvers if r], "caused_by": [c for c in causes if c]})
            paths.append({"nodes": [iid, sid], "edges": [edge_ref("AFFECTED", iid, sid)]})
            line = f"{iid} {sev} {title} ({opened[:10]}" + (f", resolved by {', '.join(items[-1]['resolved_by'])}" if items[-1]["resolved_by"] else ", open") + ")"
        elif kind == "decisions":
            did, title, ts, status, governs, mid, mname, newer, src = row
            items.append({"id": did, "title": title, "ts": ts, "status": status, "governs": governs, "made_by": mid,
                          "made_by_name": mname, "superseded_by": [n for n in newer if n]})
            paths.append({"nodes": [mid, did], "edges": [edge_ref("MADE", mid, did)]})
            line = f"{title} by {mname} ({ts[:10]}, {status})"
        else:
            aid, akind, status, ts, decided, by, sid, sname, pid, pname, blockers = row
            src = None
            items.append({"id": aid, "kind": akind, "status": status, "ts": ts, "decided_ts": decided, "proposed_by": by,
                          "target": sid, "approved_by": pid, "approved_by_name": pname, "blocked_by": [b for b in blockers if b]})
            paths.append({"nodes": [aid, sid], "edges": [edge_ref("TARGETS", aid, sid)]})
            if pid:
                paths.append({"nodes": [pid, aid], "edges": [edge_ref("APPROVED", pid, aid)]})
            line = (f"{akind} on {sname} ({status}" + (f", approved by {pname} on {decided[:10]}" if pid else "")
                    + (f", blocked by {', '.join(items[-1]['blocked_by'])}" if items[-1]["blocked_by"] else "") + ")")
        items[-1]["summary"] = line
        if src:
            sources.add(src)

    scope = f" on {service}" if service else ""
    if not items:
        explanation = f"No {kind}{scope} in the graph."
    else:
        explanation = f"Most recent {kind}{scope}, newest first: " + "; ".join(i["summary"] for i in items) + "."
        if kind == "deployments":
            explanation += " Deployments carry an author, not an approver; approvals are recorded only on actions."
        if kind == "actions" and not any(i["approved_by"] for i in items):
            explanation += " None of these was approved by a person yet."
    return ToolResult(data={"kind": kind, "service": service, "items": items}, cypher=q.strip(), params=params,
                      paths=paths, sources=sorted(sources), explanation=explanation,
                      outcome="answered" if items else "not_in_graph")
