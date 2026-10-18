"""describe (Track 03): one entity's facts, current first, each with the document it came from.

Answers "what caused inc:0042?", "what does Priya Nair work on?", "why was ADR-019 made?", "what does Team Ledger own?"
from the graph alone. State edges that ended (valid_to set) are listed separately as history, never as current facts.
Derived projections (KNOWS weights) are read for people, labelled as derived.
"""
from backend.app.graph.resolve import FACT_LABELS
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

NODE = "MATCH (n {id: $id}) RETURN labels(n)[0], properties(n)"
EDGES = """
MATCH (n {id: $id})-[r]-(m)
WHERE r.derived IS NULL AND NOT type(r) IN ['MENTIONS', 'INVOLVED', 'TARGETS', 'ABOUT']
RETURN type(r), startNode(r) = n, m.id, labels(m)[0], coalesce(m.name, m.title, m.version, m.id), m.ts,
       r.valid_from, r.valid_to, r.source_doc, m.status
ORDER BY type(r), m.id
"""
KNOWS = """
MATCH (p:Person {id: $id})-[k:KNOWS]->(s:Service)
RETURN s.id, s.name, k.weight ORDER BY k.weight DESC, s.id LIMIT 5
"""

# how a relation reads from the entity's side: (outgoing phrase, incoming phrase)
PHRASES = {
    "MEMBER_OF": ("member of", "members"), "OWNS": ("owns", "owned by"), "ON_CALL_FOR": ("on call for", "on call"),
    "DEPENDS_ON": ("depends on", "needed by"), "AUTHORED": ("authored", "authored by"),
    "DEPLOYED_TO": ("deployed to", "deployments"), "AFFECTED": ("affected", "incidents"),
    "CAUSED_BY": ("caused by", "caused"), "RESOLVED": ("resolved", "resolved by"), "MADE": ("made", "made by"),
    "GOVERNS": ("governs", "governed by"), "SUPERSEDES": ("supersedes", "superseded by"),
    "EVIDENCE_FOR": ("evidence for", "evidence"), "WROTE": ("wrote", "written by"),
}
PROPS = {"Incident": ("title", "severity", "ts_open", "ts_close", "summary"),
         "Decision": ("title", "status", "ts", "rationale", "forbids"),
         "Deployment": ("version", "ts", "status"), "Service": ("tier", "lang"), "Person": ("role",),
         "Document": ("title", "kind", "ts")}


@tool(
    name="describe",
    description="Everything the graph states about ONE entity (incident, person, team, decision, service, deployment), "
                "grouped by relation, current facts first and ended facts as history, each with its source document. "
                "Use for: what caused an incident and who resolved it; what a person works on / is on call for / knows; "
                "what a team owns and who is in it; what a decision governs, forbids, supersedes and its evidence.",
    input_schema={
        "type": "object",
        "properties": {"entity": {"type": "string", "description": "id or name: inc:0042, Priya Nair, Team Ledger, ADR-019"}},
        "required": ["entity"],
        "additionalProperties": False,
    },
    tracks=("03",),
    entities={"entity": (FACT_LABELS, "id")},
)
def describe(graph, entity: str) -> ToolResult:
    params = {"id": entity}
    label, props = ro(graph, NODE, params)[0]
    name = props.get("name") or props.get("title") or entity
    current: dict[str, list[dict]] = {}
    history, paths, sources = [], [], set()
    for rel, out, mid, mlabel, mname, mts, vf, vt, src, mstatus in ro(graph, EDGES, params):
        if mlabel == "Decision" and mstatus == "superseded":
            mname = f"{mname} (superseded)"  # a decision no longer in force must not read like one
        phrase = PHRASES.get(rel, (rel.lower(), rel.lower()))[0 if out else 1]
        fact = {"relation": rel, "reads": phrase, "id": mid, "label": mlabel, "name": mname, "source": src,
                **({"ts": mts} if mts else {}), **({"since": vf} if vf else {})}
        src_id, dst_id = (entity, mid) if out else (mid, entity)
        if vt is not None:  # a state fact that ended: history, not a current fact
            history.append(fact | {"valid_to": vt})
            paths.append({"nodes": [src_id, dst_id], "edges": [edge_ref(rel, src_id, dst_id)], "superseded": True})
        else:
            current.setdefault(phrase, []).append(fact)
            paths.append({"nodes": [src_id, dst_id], "edges": [edge_ref(rel, src_id, dst_id)]})
        if src:
            sources.add(src)
        if mlabel == "Document" and rel in ("EVIDENCE_FOR", "WROTE"):
            sources.add(mid)
    knows = []
    if label == "Person":
        knows = [{"id": s, "name": n, "weight": w} for s, n, w in ro(graph, KNOWS, params)]
    attrs = {k: props[k] for k in PROPS.get(label, ()) if props.get(k) not in (None, "", [])}

    parts = [f"{phrase} {', '.join(f['name'] for f in facts)}" for phrase, facts in current.items()]
    if knows:
        parts.append("knows (derived) " + ", ".join(k["name"] for k in knows))
    detail = "; ".join(parts) if parts else "no current facts"
    head = f"{label} {name} ({entity})" + (f" [{', '.join(f'{k}: {v}' for k, v in attrs.items() if k != 'summary' and k != 'rationale')}]"
                                           if attrs else "")
    reach, reach_text = {}, ""
    if label in REACH:  # the multi-hop consequence of this entity (see REACH)
        row = ro(graph, REACH[label], params)
        reach, reach_text = _reach(label, row[0] if row else None)
    return ToolResult(
        data={"id": entity, "label": label, "name": name, "attributes": attrs, "current": current,
              "history": history, "knows": knows, "reach": reach},
        cypher=NODE + "\n\n" + EDGES.strip() + ("\n\n" + KNOWS.strip() if label == "Person" else "")
               + ("\n\n" + REACH[label].strip() if label in REACH else ""),
        params=params, paths=paths, sources=sorted(sources),
        explanation=f"{head}: {detail}." + reach_text
                    + (f" {len(history)} ended fact(s) kept as history." if history else ""),
    )


# What each kind of entity reaches through the graph, beyond its own edges (current DEPENDS_ON only, 3 hops):
#   Service   what it needs (upstream) and what needs it (downstream)
#   Team      other teams whose services depend on this team's services
#   Incident  everything downstream of the services it affected
#   Decision  the full SUPERSEDES chain it ends, and every service its constraint protects downstream
#   Person    the services that depend on what this person knows (their knowledge's blast radius)
CURRENT_DEPS = "all(r IN relationships(reach) WHERE r.valid_to IS NULL)"
REACH = {
    "Service": f"""
MATCH (s:Service {{id: $id}})
OPTIONAL MATCH reach=(s)-[:DEPENDS_ON*1..3]->(u:Service) WHERE {CURRENT_DEPS}
WITH s, collect(DISTINCT u.id) AS upstream
OPTIONAL MATCH reach=(x:Service)-[:DEPENDS_ON*1..3]->(s) WHERE {CURRENT_DEPS}
RETURN upstream, collect(DISTINCT x.id)""",
    "Team": f"""
MATCH (t:Team {{id: $id}})-[o:OWNS]->(s:Service) WHERE o.valid_to IS NULL
MATCH reach=(x:Service)-[:DEPENDS_ON*1..3]->(s) WHERE {CURRENT_DEPS}
MATCH (ot:Team)-[oo:OWNS]->(x) WHERE oo.valid_to IS NULL AND ot <> t
RETURN collect(DISTINCT ot.name), count(DISTINCT x)""",
    "Incident": f"""
MATCH (i:Incident {{id: $id}})-[:AFFECTED]->(s:Service)
OPTIONAL MATCH reach=(x:Service)-[:DEPENDS_ON*1..3]->(s) WHERE {CURRENT_DEPS}
RETURN collect(DISTINCT s.id), collect(DISTINCT x.id)""",
    "Decision": f"""
MATCH (d:Decision {{id: $id}})
OPTIONAL MATCH (d)-[:SUPERSEDES*1..5]->(old:Decision)
WITH d, collect(DISTINCT old.id) AS supersedes
OPTIONAL MATCH (d)-[:GOVERNS]->(s:Service)
OPTIONAL MATCH reach=(x:Service)-[:DEPENDS_ON*1..3]->(s) WHERE {CURRENT_DEPS}
RETURN supersedes, collect(DISTINCT s.id), collect(DISTINCT x.id)""",
    "Person": f"""
MATCH (p:Person {{id: $id}})-[:KNOWS]->(s:Service)
OPTIONAL MATCH reach=(x:Service)-[:DEPENDS_ON*1..3]->(s) WHERE {CURRENT_DEPS}
RETURN collect(DISTINCT s.id), collect(DISTINCT x.id)""",
}


def _reach(label: str, row) -> tuple[dict, str]:
    if not row:
        return {}, ""
    if label == "Service":
        up, down = sorted(row[0]), sorted(row[1])
        return ({"upstream_3_hops": up, "downstream_3_hops": down},
                f" Within 3 hops it needs {len(up)} service(s) and {len(down)} service(s) need it.")
    if label == "Team":
        teams, n = sorted(row[0]), row[1]
        return ({"dependent_teams": teams, "dependent_services": n},
                f" {n} service(s) of {len(teams)} other team(s) depend on its services within 3 hops"
                + (f" ({', '.join(teams)})." if teams else "."))
    if label == "Incident":
        hit, down = sorted(row[0]), sorted(row[1])
        return ({"affected": hit, "downstream_3_hops": down},
                f" Downstream of what it hit: {len(down)} service(s) within 3 hops" + (f" ({', '.join(down[:6])})." if down else "."))
    if label == "Decision":
        chain, governs, down = row[0], sorted(row[1]), sorted(row[2])
        return ({"supersedes_chain": chain, "governs": governs, "protected_downstream": down},
                (f" It supersedes {' -> '.join(chain)}." if chain else "")
                + f" Its constraint protects {len(governs) + len(down)} service(s): {len(governs)} governed directly"
                + f" and {len(down)} depending on them within 3 hops.")
    knows, down = sorted(row[0]), sorted(row[1])
    return ({"knows": knows, "dependents_of_known": down},
            f" {len(down)} service(s) depend within 3 hops on what this person knows.")
