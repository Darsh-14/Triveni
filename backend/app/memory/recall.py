"""Recall (Track 02): find past Episodes through shared graph entities, not text search.

The query entities are expanded one hop along AFFECTED, so a brand-new incident on payments-api still reaches
episodes about payments-api (and an episode about a service reaches incidents on it).
"""
from falkordb import Graph

EXPAND = """
MATCH (x) WHERE x.id IN $ids
OPTIONAL MATCH (x)-[:AFFECTED]-(y)
RETURN collect(DISTINCT x.id) + collect(DISTINCT y.id)
"""

RECALL = """
MATCH (e:Episode)-[:INVOLVED]->(x) WHERE x.id IN $ids
WITH e, collect(DISTINCT x.id) AS shared
OPTIONAL MATCH (e)-[:LEARNED]->(l:Lesson)
OPTIONAL MATCH (e)-[:USED]->(p:Procedure)
OPTIONAL MATCH (a:Agent)-[:RAN]->(e)
RETURN e.id, e.ts, e.question, e.outcome, shared, a.id,
       collect(DISTINCT {id: l.id, text: l.text, confidence: l.confidence}) AS lessons,
       collect(DISTINCT {id: p.id, name: p.name, steps: p.steps, success_count: p.success_count, fail_count: p.fail_count}) AS procedures
ORDER BY size(shared) DESC, e.ts DESC
LIMIT $limit
"""


def recall(graph: Graph, entities: list[str], limit: int = 5) -> dict:
    ids = graph.ro_query(EXPAND, {"ids": entities}).result_set[0][0]
    ids = sorted({i for i in ids if i})
    episodes = []
    for eid, ts, question, outcome, shared, agent, lessons, procedures in graph.ro_query(RECALL, {"ids": ids, "limit": limit}).result_set:
        episodes.append({
            "id": eid, "ts": ts, "question": question, "outcome": outcome, "agent": agent, "shared": sorted(shared),
            "lessons": [x for x in lessons if x["id"]],
            "procedures": [p | {"success_rate": round(p["success_count"] / max(1, p["success_count"] + p["fail_count"]), 2)}
                           for p in procedures if p["id"]],
        })
    return {"query": entities, "expanded": ids, "episodes": episodes}
