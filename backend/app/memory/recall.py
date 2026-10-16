"""Recall (Track 02): find past Episodes through shared graph entities, not text search.

The query entities are expanded one hop along AFFECTED, so a brand-new incident on payments-api still reaches
episodes about payments-api (and an episode about a service reaches incidents on it).

Memory decays. A lesson's stored confidence is what was learned; when it is read, it is weighted by how long ago it
was last reinforced: effective = confidence x 0.5^(age_days / half_life). Lessons below FADED are still returned
but flagged, so the agent can say "we learned this once, long ago". Episodes are ranked by shared entities first,
then by the same recency weight. Nothing is deleted.
"""
import os
from datetime import datetime, timezone

from falkordb import Graph

HALF_LIFE_DAYS = float(os.getenv("TRIVENI_MEMORY_HALF_LIFE_DAYS", "90"))
FADED = 0.15

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
       collect(DISTINCT {id: l.id, text: l.text, confidence: l.confidence, last_reinforced: l.last_reinforced}) AS lessons,
       collect(DISTINCT {id: p.id, name: p.name, steps: p.steps, success_count: p.success_count, fail_count: p.fail_count}) AS procedures
ORDER BY size(shared) DESC, e.ts DESC
LIMIT $candidates
"""


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if ts else None
    except ValueError:
        return None


def recency(ts: str | None, now: datetime, half_life: float = HALF_LIFE_DAYS) -> float:
    """0.5^(age / half_life): 1.0 today, 0.5 after one half-life."""
    then = _parse(ts)
    if then is None:
        return 1.0
    age_days = max(0.0, (now - then).total_seconds() / 86400)
    return 0.5 ** (age_days / half_life)


def recall(graph: Graph, entities: list[str], limit: int = 5, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ids = graph.ro_query(EXPAND, {"ids": entities}).result_set[0][0]
    ids = sorted({i for i in ids if i})
    episodes = []
    rows = graph.ro_query(RECALL, {"ids": ids, "candidates": max(limit * 4, 20)}).result_set
    for eid, ts, question, outcome, shared, agent, lessons, procedures in rows:
        lessons = [x for x in lessons if x["id"]]
        for lesson in lessons:
            weight = recency(lesson["last_reinforced"], now)
            lesson["effective_confidence"] = round(lesson["confidence"] * weight, 2)
            lesson["faded"] = lesson["effective_confidence"] < FADED
        weight = recency(ts, now)
        episodes.append({
            "id": eid, "ts": ts, "question": question, "outcome": outcome, "agent": agent, "shared": sorted(shared),
            "recency": round(weight, 2), "score": round(len(shared) + weight, 2),
            "lessons": sorted(lessons, key=lambda x: -x["effective_confidence"]),
            "procedures": [p | {"success_rate": round(p["success_count"] / max(1, p["success_count"] + p["fail_count"]), 2)}
                           for p in procedures if p["id"]],
        })
    episodes.sort(key=lambda e: (-e["score"], e["id"]))
    return {"query": entities, "expanded": ids, "half_life_days": HALF_LIFE_DAYS, "episodes": episodes[:limit]}
