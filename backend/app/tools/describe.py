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
    return ToolResult(
        data={"id": entity, "label": label, "name": name, "attributes": attrs, "current": current,
              "history": history, "knows": knows},
        cypher=NODE + "\n\n" + EDGES.strip() + ("\n\n" + KNOWS.strip() if label == "Person" else ""),
        params=params, paths=paths, sources=sorted(sources),
        explanation=f"{head}: {detail}." + (f" {len(history)} ended fact(s) kept as history." if history else ""),
    )
