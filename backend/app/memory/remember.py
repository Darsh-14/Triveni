"""Episodic, semantic and procedural memory (Track 02).

  Episode   what happened (question, outcome), linked to the entities it INVOLVED and the Agent that RAN it
  Lesson    what was learned; the same lesson learned again is reinforced (confidence up), not duplicated;
            a failed procedure weakens the lessons learned alongside it; age is applied on read (recall.py)
  Procedure how it was fixed; reused by name, with success_count / fail_count updated from outcomes
"""
from falkordb import Graph

from backend.app.memory.conversation import new_id, now

EPISODE = """
MATCH (a:Agent {id: $agent})
CREATE (a)-[:RAN {ts: $ts}]->(e:Episode {id: $eid, ts: $ts, question: $question, outcome: $outcome})
WITH e
UNWIND $involved AS xid
MATCH (x {id: xid}) WHERE x:Service OR x:Incident OR x:Person
CREATE (e)-[:INVOLVED {ts: $ts}]->(x)
RETURN count(x)
"""

LESSON = """
MATCH (e:Episode {id: $eid})
MERGE (l:Lesson {text: $text})
ON CREATE SET l.id = $lid, l.confidence = 0.6, l.last_reinforced = $ts
ON MATCH SET l.confidence = CASE WHEN l.confidence + 0.1 > 1.0 THEN 1.0 ELSE l.confidence + 0.1 END,
             l.last_reinforced = $ts
CREATE (e)-[:LEARNED {ts: $ts}]->(l)
RETURN l.id, l.confidence
"""

PROCEDURE = """
MATCH (e:Episode {id: $eid})
MERGE (p:Procedure {name: $name})
ON CREATE SET p.id = $pid, p.steps = $steps, p.success_count = 0, p.fail_count = 0
SET p.success_count = p.success_count + $ok, p.fail_count = p.fail_count + $failed
CREATE (e)-[:USED {ts: $ts}]->(p)
RETURN p.id, p.success_count, p.fail_count
"""

PROCEDURE_FOR = """
MATCH (p:Procedure {id: $pid})
UNWIND $services AS sid
MATCH (s:Service {id: sid})
MERGE (p)-[f:FOR]->(s) ON CREATE SET f.ts = $ts
RETURN count(s)
"""


# A procedure that failed weakens what was learned in the episodes that used it (persisted; floor 0.05)
CONTRADICT = """
MATCH (p:Procedure {id: $pid})<-[:USED]-(e:Episode)-[:LEARNED]->(l:Lesson)
WITH DISTINCT l
SET l.confidence = CASE WHEN l.confidence - 0.15 < 0.05 THEN 0.05 ELSE l.confidence - 0.15 END
RETURN l.id, l.confidence
"""


def remember(graph: Graph, agent: str, question: str, outcome: str, involved: list[str],
             lesson: str | None = None, procedure: dict | None = None, procedure_result: str | None = None) -> dict:
    """Write one Episode (+ optional Lesson / Procedure). procedure = {"name", "steps": [...]}."""
    ts, eid = now(), new_id("ep")
    linked = graph.query(EPISODE, {"agent": agent, "ts": ts, "eid": eid, "question": question,
                                   "outcome": outcome, "involved": involved}).result_set
    out = {"episode": eid, "involved": linked[0][0] if linked else 0}
    if lesson:
        lid, conf = graph.query(LESSON, {"eid": eid, "text": lesson.strip(), "lid": new_id("lesson"), "ts": ts}).result_set[0]
        out["lesson"] = {"id": lid, "confidence": round(conf, 2)}
    if procedure and procedure.get("name"):
        pid, ok, failed = graph.query(PROCEDURE, {
            "eid": eid, "name": procedure["name"].strip(), "pid": new_id("proc"), "steps": list(procedure.get("steps") or []),
            "ok": 1 if procedure_result == "success" else 0, "failed": 1 if procedure_result == "fail" else 0, "ts": ts,
        }).result_set[0]
        services = [x for x in involved if x.startswith("svc:")]
        if services:
            graph.query(PROCEDURE_FOR, {"pid": pid, "services": services, "ts": ts})
        out["procedure"] = {"id": pid, "success_count": ok, "fail_count": failed}
        if procedure_result == "fail":
            out["weakened_lessons"] = [{"id": i, "confidence": round(c, 2)}
                                       for i, c in graph.query(CONTRADICT, {"pid": pid}).result_set]
    return out
