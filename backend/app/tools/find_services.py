"""find_services (Track 01 / 03): services filtered by attributes and current responsibility, deterministically.

The fixed, parameterized counterpart to graph_query for the most common open questions: "which tier-1 services have
nobody on call?", "python services owned by Team Ledger", "services without an owner". Every filter is optional and is
a parameter (null = no filter), so one human-written query covers all combinations, works without a model, and only
current OWNS / ON_CALL_FOR edges count.
"""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

FIND = """
MATCH (s:Service)
WHERE ($tier IS NULL OR s.tier = $tier) AND ($lang IS NULL OR toLower(s.lang) = toLower($lang))
OPTIONAL MATCH (t:Team)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(s) WHERE c.valid_to IS NULL
WITH s, collect(DISTINCT t) AS teams, collect(DISTINCT p) AS oncall
WHERE ($team IS NULL OR any(x IN teams WHERE x.id = $team))
  AND ($has_owner IS NULL OR (size(teams) > 0) = $has_owner)
  AND ($has_on_call IS NULL OR (size(oncall) > 0) = $has_on_call)
OPTIONAL MATCH (d:Service)-[r:DEPENDS_ON]->(s) WHERE r.valid_to IS NULL
RETURN s.id, s.name, s.tier, s.lang, [x IN teams | x.id], [x IN teams | x.name], [x IN oncall | x.id],
       [x IN oncall | x.name], count(d) AS dependents
ORDER BY s.tier, dependents DESC, s.id
LIMIT $limit
"""


@tool(
    name="find_services",
    description="Services matching attribute filters, each with its current owner, on-call and number of dependents: "
                "tier (1-3), lang, owning team, has_owner, has_on_call. Use for 'which tier-1 services have nobody on "
                "call', 'kotlin services owned by Ledger', 'services without an owner'. All filters are optional.",
    input_schema={
        "type": "object",
        "properties": {
            "tier": {"type": "integer", "enum": [1, 2, 3]},
            "lang": {"type": "string", "description": "e.g. python, go, java, kotlin, typescript"},
            "team": {"type": "string", "description": "owning team id or name, e.g. Ledger"},
            "has_owner": {"type": "boolean"},
            "has_on_call": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
        },
        "additionalProperties": False,
    },
    tracks=("01", "03"),
    entities={"team": (("Team",), "id")},
)
def find_services(graph, tier: int | None = None, lang: str | None = None, team: str | None = None,
                  has_owner: bool | None = None, has_on_call: bool | None = None, limit: int = 20) -> ToolResult:
    params = {"tier": tier, "lang": lang, "team": team, "has_owner": has_owner, "has_on_call": has_on_call,
              "limit": max(1, min(int(limit), 50))}
    items, paths = [], []
    for sid, name, t, lg, team_ids, team_names, oc_ids, oc_names, deps in ro(graph, FIND, params):
        items.append({"id": sid, "name": name, "tier": t, "lang": lg, "owners": team_ids, "owner_names": team_names,
                      "on_call": oc_ids, "on_call_names": oc_names, "dependents": deps})
        paths += [{"nodes": [o, sid], "edges": [edge_ref("OWNS", o, sid)]} for o in team_ids]
        paths += [{"nodes": [p, sid], "edges": [edge_ref("ON_CALL_FOR", p, sid)]} for p in oc_ids]
        if not team_ids and not oc_ids:
            paths.append({"nodes": [sid], "edges": []})
    filters = ", ".join(f"{k}={v}" for k, v in params.items() if v is not None and k != "limit") or "no filter"
    listed = "; ".join(f"{i['name']} (tier {i['tier']}, {i['lang']}, owner {', '.join(i['owner_names']) or 'none'}, "
                       f"on call {', '.join(i['on_call_names']) or 'nobody'}, {i['dependents']} dependents)" for i in items[:10])
    return ToolResult(
        data={"filters": {k: v for k, v in params.items() if v is not None}, "services": items},
        cypher=FIND.strip(), params=params, paths=paths,
        explanation=(f"{len(items)} service(s) match {filters} (current edges only): {listed}." if items
                     else f"No service matches {filters} (current edges only)."),
        outcome="answered" if items else "not_in_graph",
    )
