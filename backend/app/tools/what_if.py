"""what_if (Track 01 + 03): counterfactuals on a throwaway copy of the tenant graph.

"What if Priya leaves?" / "What if Team Ledger is dissolved?" / "What if we decommission legacy-fax-gateway?"
The tenant graph is copied with FalkorDB's GRAPH.COPY (~0.1 s), the hypothetical change is applied to the copy
only, the derived projections are rebuilt there, and the same algorithms run before and after:
betweenness (single points of knowledge), WCC (orphans), expertise coverage per service, blast radius. The answer
is the difference. The copy is deleted afterwards; the real graph is never written.
"""
import uuid

from backend.app.graph.client import get_db
from backend.app.graph.projections import refresh_projections
from backend.app.graph.resolve import FACT_LABELS
from backend.app.tools.base import ToolResult, edge_ref, ro, tool
from backend.app.tools.blast_radius import blast_radius
from backend.app.tools.find_orphans import find_orphans
from backend.app.tools.key_people import key_people

SCENARIOS = {
    # kind: (label the entity must have, Cypher applied to the COPY)
    "person_leaves": ("Person", "MATCH (x:Person {id: $id}) DETACH DELETE x"),
    "team_dissolved": ("Team", "MATCH (x:Team {id: $id}) DETACH DELETE x"),
    "service_decommissioned": ("Service", "MATCH (x:Service {id: $id}) DETACH DELETE x"),
}
PREFIX = {"Person": "per:", "Team": "team:", "Service": "svc:"}

LABEL = "MATCH (x {id: $id}) RETURN labels(x)[0], coalesce(x.name, x.title)"
COVERAGE = "MATCH (s:Service) OPTIONAL MATCH (p:Person)-[:KNOWS]->(s) RETURN s.id, s.name, collect(p.id)"
PERSON_FOOTPRINT = """
MATCH (p:Person {id: $id})
OPTIONAL MATCH (p)-[k:KNOWS]->(s:Service)
OPTIONAL MATCH (p)-[c:ON_CALL_FOR]->(oc:Service) WHERE c.valid_to IS NULL
RETURN collect(DISTINCT s.id), collect(DISTINCT oc.id)
"""
TEAM_FOOTPRINT = """
MATCH (t:Team {id: $id})
OPTIONAL MATCH (t)-[o:OWNS]->(s:Service) WHERE o.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[m:MEMBER_OF]->(t) WHERE m.valid_to IS NULL
RETURN collect(DISTINCT s.id), collect(DISTINCT p.id)
"""


def _snapshot(graph) -> dict:
    coverage = {sid: (name, sorted(p for p in people if p)) for sid, name, people in ro(graph, COVERAGE, {})}
    return {
        "coverage": coverage,
        "orphans": {o["id"] for o in find_orphans(graph).data["orphans"]},
        "key_people": [(p["id"], p["name"], p["score"]) for p in key_people(graph, limit=5).data["people"]],
    }


@tool(
    name="what_if",
    description="Counterfactual simulation on a throwaway copy of the graph: what happens if a person leaves "
                "(person_leaves), a team is dissolved (team_dissolved) or a service is decommissioned "
                "(service_decommissioned). Returns what changes: services left with no one who knows them, services "
                "that drop to a single expert, newly orphaned services, new single points of knowledge, and (for a "
                "service) what depends on it. The real graph is never modified.",
    input_schema={
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "enum": list(SCENARIOS)},
            "entity": {"type": "string", "description": "id or name: per:priya-nair, team:ledger, svc:legacy-fax-gateway"},
        },
        "required": ["scenario", "entity"],
        "additionalProperties": False,
    },
    tracks=("01", "03"),
    entities={"entity": (lambda a: (SCENARIOS[a["scenario"]][0],) if a.get("scenario") in SCENARIOS else FACT_LABELS, "id")},
)
def what_if(graph, scenario: str, entity: str) -> ToolResult:
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {list(SCENARIOS)}")
    label, change = SCENARIOS[scenario]
    eid = entity if ":" in entity else PREFIX[label] + entity.strip().lower().replace(" ", "-")
    found = ro(graph, LABEL, {"id": eid})
    if not found or found[0][0] != label:
        raise ValueError(f"{eid} is not a {label} in this tenant")
    name = found[0][1]

    before = _snapshot(graph)
    footprint = {}
    if label == "Person":
        knows, oncall = ro(graph, PERSON_FOOTPRINT, {"id": eid})[0]
        footprint = {"knows": sorted(knows), "on_call_for": sorted(oncall)}
    elif label == "Team":
        owned, members = ro(graph, TEAM_FOOTPRINT, {"id": eid})[0]
        footprint = {"owns": sorted(owned), "members": sorted(members)}
    else:
        dependents = blast_radius(graph, eid, depth=3).data["affected"]
        footprint = {"dependents": [{"id": d["id"], "hops": d["hops"], "team": d.get("team")} for d in dependents]}

    sandbox_name = f"{graph.name}__whatif_{uuid.uuid4().hex[:6]}"
    graph.copy(sandbox_name)  # GRAPH.COPY: the sandbox is a separate graph
    sandbox = get_db().select_graph(sandbox_name)
    try:
        sandbox.query(change, {"id": eid})
        refresh_projections(sandbox)  # expertise / responsibility recomputed from what is left
        after = _snapshot(sandbox)
    finally:
        sandbox.delete()

    def knowers(snap, sid):
        return snap["coverage"].get(sid, ("", []))[1]

    services = [s for s in before["coverage"] if s != eid]
    knowledge_lost = [s for s in services if knowers(before, s) and not knowers(after, s)]
    single_expert = [s for s in services if len(knowers(before, s)) > 1 and len(knowers(after, s)) == 1]
    new_orphans = sorted(after["orphans"] - before["orphans"] - {eid})
    top_before = {p for p, _, _ in before["key_people"][:3]}
    new_key_people = [{"id": p, "name": n, "score": s} for p, n, s in after["key_people"][:3] if p not in top_before]

    paths = []
    if label == "Person":
        paths += [{"nodes": [eid, s], "edges": [edge_ref("KNOWS", eid, s)], "superseded": True} for s in footprint["knows"]]
    elif label == "Team":
        paths += [{"nodes": [eid, s], "edges": [edge_ref("OWNS", eid, s)], "superseded": True} for s in footprint["owns"]]
    else:
        paths += [{"nodes": [d["id"], eid], "edges": [edge_ref("DEPENDS_ON", d["id"], eid)], "superseded": True}
                  for d in footprint["dependents"] if d["hops"] == 1]
    for s in single_expert:
        paths += [{"nodes": [p, s], "edges": [edge_ref("KNOWS", p, s)]} for p in knowers(after, s)]
    paths += [{"nodes": [s], "edges": []} for s in knowledge_lost + new_orphans]

    data = {
        "scenario": scenario, "entity": eid, "name": name, "footprint": footprint,
        "knowledge_lost": [{"id": s, "name": before["coverage"][s][0], "knew": knowers(before, s)} for s in knowledge_lost],
        "single_expert_now": [{"id": s, "name": before["coverage"][s][0], "only_expert": knowers(after, s)[0]} for s in single_expert],
        "new_orphans": new_orphans,
        "new_key_people": new_key_people,
        "key_people_before": [{"id": p, "score": s} for p, _, s in before["key_people"][:3]],
        "key_people_after": [{"id": p, "score": s} for p, _, s in after["key_people"][:3]],
        "sandbox": "GRAPH.COPY of the tenant graph, deleted after the run",
    }
    bits = [f"If {name} {'leaves' if label == 'Person' else 'is dissolved' if label == 'Team' else 'is decommissioned'}:"]
    if label == "Service":
        bits.append(f"{len(footprint['dependents'])} service(s) depend on it within 3 hops;")
    bits.append(f"{len(knowledge_lost)} service(s) left with nobody who knows them"
                + (f" ({', '.join(before['coverage'][s][0] for s in knowledge_lost)})" if knowledge_lost else "") + ";")
    bits.append(f"{len(single_expert)} drop to a single expert;")
    bits.append(f"{len(new_orphans)} newly orphaned" + (f" ({', '.join(new_orphans)})" if new_orphans else "") + ";")
    bits.append("new single points of knowledge: " + (", ".join(f"{p['name']} ({p['score']})" for p in new_key_people) or "none") + ".")
    return ToolResult(data=data, cypher="\n\n".join(["GRAPH.COPY <tenant graph> <sandbox>", change, "-- then refresh_projections() "
                      "on the sandbox and, before and after:", COVERAGE, "CALL algo.betweenness(...)  -- key_people",
                      "CALL algo.WCC(...)  -- find_orphans"]), params={"id": eid, "scenario": scenario},
                      paths=paths, explanation=" ".join(bits))
