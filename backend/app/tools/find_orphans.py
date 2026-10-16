"""find_orphans (Track 01 + 03): services nobody is responsible for, found as singleton connected components of the
derived responsibility projection (Team/Person -[RESPONSIBLE_FOR]-> Service, rebuilt from current OWNS/ON_CALL_FOR)."""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

# algo.WCC({nodeLabels, relationshipTypes}) YIELD node, componentId; isolated nodes get their own component
WCC = """
CALL algo.WCC({nodeLabels: ['Team', 'Person', 'Service'], relationshipTypes: ['RESPONSIBLE_FOR']})
YIELD node, componentId
WITH componentId, collect(node) AS members
WITH componentId, members, size(members) AS n
RETURN componentId, n, [m IN members WHERE m:Service | m.id] AS services
"""

RISK = """
MATCH (s:Service) WHERE s.id IN $ids
OPTIONAL MATCH (d:Service)-[r:DEPENDS_ON]->(s) WHERE r.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[k:KNOWS]->(s)
OPTIONAL MATCH (x)-[old:OWNS|ON_CALL_FOR]->(s) WHERE old.valid_to IS NOT NULL
RETURN s.id, s.name, s.tier, collect(DISTINCT d.id), collect(DISTINCT p.name), collect(DISTINCT x.id)
"""


@tool(
    name="find_orphans",
    description="Services with no current owning team and no on-call engineer (singleton components of the "
                "responsibility graph), with what depends on them, who still knows them, and who used to own them.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    tracks=("01", "03"),
)
def find_orphans(graph) -> ToolResult:
    components = ro(graph, WCC, {})
    orphan_ids = sorted(sid for _, n, services in components if n == 1 for sid in services)
    params = {"ids": orphan_ids}
    orphans, paths = [], []
    for sid, name, tier, deps, knowers, former in (ro(graph, RISK, params) if orphan_ids else []):
        deps = sorted(d for d in deps if d)
        orphans.append({"id": sid, "name": name, "tier": tier, "dependents": deps,
                        "known_by": sorted(k for k in knowers if k), "former_owners": sorted(f for f in former if f)})
        paths += [{"nodes": [d, sid], "edges": [edge_ref("DEPENDS_ON", d, sid)]} for d in deps]
    orphans.sort(key=lambda o: (-len(o["dependents"]), o["id"]))
    explanation = (f"{len(orphans)} orphan service(s) out of {len(components)} responsibility components: "
                   + ", ".join(f"{o['name']} ({len(o['dependents'])} dependents)" for o in orphans) + "."
                   if orphans else f"Every service has an owner or on-call ({len(components)} components).")
    return ToolResult(data={"orphans": orphans, "components": len(components),
                            "algorithm": "algo.WCC on RESPONSIBLE_FOR (derived from current OWNS/ON_CALL_FOR)"},
                      cypher=WCC.strip() + "\n\n" + RISK.strip(), params=params, paths=paths, explanation=explanation)
