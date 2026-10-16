"""key_people (Track 01 + 03): single points of knowledge, i.e. people whose expertise is the only bridge between
groups of services. Betweenness centrality over the derived expertise projection (KNOWS / KNOWN_BY)."""
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

# FalkorDB samples source nodes *with replacement* (measured on Cloud, Oct 16): a sample the size of the graph does
# not cover every node, and scores change with the seed. From ~2000 samples the top-2 set is stable on every seed,
# so we sample at least that many with a fixed seed, and report the scores as sampled estimates.
MIN_SAMPLES, SEED = 2000, 42

BETWEENNESS = """
CALL algo.betweenness({nodeLabels: ['Person', 'Service'], relationshipTypes: ['KNOWS', 'KNOWN_BY'],
                       samplingSize: $samples, samplingSeed: $seed})
YIELD node, score
WITH node, score WHERE node:Person AND score > 0
RETURN node.id, node.name, score
ORDER BY score DESC, node.id
LIMIT %d
"""
SIZE = "MATCH (n) WHERE n:Person OR n:Service RETURN count(n)"

SPANS = """
MATCH (p:Person)-[k:KNOWS]->(s:Service) WHERE p.id IN $ids
OPTIONAL MATCH (t:Team)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
OPTIONAL MATCH (p)-[m:MEMBER_OF]->(home:Team) WHERE m.valid_to IS NULL
RETURN p.id, home.name, s.id, s.name, t.name, k.weight
"""


@tool(
    name="key_people",
    description="Single points of knowledge: people with the highest betweenness on the expertise graph (people <-> "
                "services they know). A high score means knowledge between groups of services flows only through that "
                "person. Shows which teams' services each person spans.",
    input_schema={
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
        "additionalProperties": False,
    },
    tracks=("01", "03"),
)
def key_people(graph, limit: int = 5) -> ToolResult:
    limit = max(1, min(int(limit), 20))
    size = ro(graph, SIZE, {})[0][0]
    params = {"samples": max(MIN_SAMPLES, 20 * size), "seed": SEED}
    q = BETWEENNESS % limit
    people = [{"id": i, "name": n, "score": round(s, 1)} for i, n, s in ro(graph, q, params)]
    by_id = {p["id"]: p | {"home_team": None, "knows": [], "teams_spanned": []} for p in people}
    paths = []
    for pid, home, sid, sname, owner, weight in ro(graph, SPANS, {"ids": list(by_id)}):
        p = by_id[pid]
        p["home_team"] = home
        p["knows"].append({"service": sid, "name": sname, "owner": owner, "weight": weight})
        paths.append({"nodes": [pid, sid], "edges": [edge_ref("KNOWS", pid, sid)]})
    for p in by_id.values():
        p["teams_spanned"] = sorted({k["owner"] for k in p["knows"] if k["owner"]})
        p["knows"].sort(key=lambda k: -k["weight"])
    ranked = [by_id[p["id"]] for p in people]
    bridges = [p for p in ranked if len(p["teams_spanned"]) > 1]
    explanation = ("Top single points of knowledge (sampled betweenness): "
                   + ", ".join(f"{p['name']} ({p['score']}, spans {'/'.join(p['teams_spanned']) or '-'})" for p in ranked[:3])
                   + (f". {len(bridges)} of them know services in more than one team." if bridges else "."))
    return ToolResult(
        data={"people": ranked, "algorithm": "algo.betweenness on KNOWS/KNOWN_BY (derived from current facts)",
              "samples": params["samples"], "seed": SEED, "note": "scores are sampled estimates; compare ranks, not values"},
        cypher=q.strip() + "\n\n" + SPANS.strip(), params=params | {"ids": list(by_id)}, paths=paths, explanation=explanation)
