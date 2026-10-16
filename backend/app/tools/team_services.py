"""team_services (Track 03): what a team currently owns, with on-call and runbooks that cite superseded decisions."""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

OWNED = """
MATCH (t:Team)-[o:OWNS]->(s:Service) WHERE (t.id = $team OR toLower(t.name) = toLower($team)) AND o.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(s) WHERE c.valid_to IS NULL
RETURN t.id, t.name, s.id, s.name, o.valid_from, o.source_doc, p.id, p.name
ORDER BY s.name
"""

# runbooks that MENTION a decision which has been superseded and which GOVERNS one of the team's services
STALE = """
MATCH (doc:Document {kind: 'runbook'})-[:MENTIONS]->(old:Decision)-[:GOVERNS]->(s:Service) WHERE s.id IN $ids
MATCH (newer:Decision)-[:SUPERSEDES]->(old)
RETURN s.id, doc.id, doc.title, old.id, newer.id
"""


@tool(
    name="team_services",
    description="Services a team currently owns (by team id like team:atlas or name like Atlas), each with its on-call "
                "engineer, when the team took it over and from which source, and any runbooks that are out of date "
                "because they cite a superseded decision.",
    input_schema={
        "type": "object",
        "properties": {"team": {"type": "string", "description": "team id or name, e.g. team:atlas or Atlas"}},
        "required": ["team"],
        "additionalProperties": False,
    },
    tracks=("03",),
)
def team_services(graph, team: str) -> ToolResult:
    team = team.removeprefix("Team ").strip()
    params = {"team": team}
    services, paths, sources, team_id = {}, [], set(), None
    for tid, tname, sid, sname, since, src, pid, pname in ro(graph, OWNED, params):
        team_id = tid
        services[sid] = {"id": sid, "name": sname, "since": since, "source": src, "on_call": pid, "on_call_name": pname,
                         "stale_runbooks": []}
        paths.append({"nodes": [tid, sid], "edges": [edge_ref("OWNS", tid, sid)]})
        sources |= {src} if src else set()
    for sid, doc, title, old, newer in (ro(graph, STALE, {"ids": list(services)}) if services else []):
        services[sid]["stale_runbooks"].append({"document": doc, "title": title, "cites": old, "superseded_by": newer})
        paths.append({"nodes": [doc, old], "edges": [edge_ref("MENTIONS", doc, old)], "stale": True})
        sources.add(doc)
    stale = [r["document"] for s in services.values() for r in s["stale_runbooks"]]
    return ToolResult(
        data={"team": team_id or team, "services": list(services.values()), "stale_runbooks": stale},
        cypher=OWNED.strip() + "\n\n" + STALE.strip(), params=params | {"ids": list(services)}, paths=paths, sources=sorted(sources),
        explanation=(f"{team_id} currently owns {len(services)} service(s): {', '.join(s['name'] for s in services.values())}; "
                     f"stale runbooks: {', '.join(stale) or 'none'}.") if services else f"No current services for team {team}.")
