"""Agent coordination through the graph only (Track 02).

Agents never call each other and share no process state. Triage writes a Handoff node addressed to Remediation;
Remediation claims it in ONE statement that matches status 'open' and sets 'claimed' (FalkorDB runs write queries
on a graph one at a time, so two claimers can never both win), works on it, and marks it done.
"""
import json

from falkordb import Graph

from backend.app.memory.conversation import new_id, now

AGENTS = ("agent:triage", "agent:remediation")

CREATE = """
MATCH (src:Agent {id: $from}), (dst:Agent {id: $to})
OPTIONAL MATCH (i:Incident {id: $incident})
CREATE (src)-[:CREATED {ts: $ts}]->(h:Handoff {id: $id, ts: $ts, status: 'open', payload: $payload})-[:TO {ts: $ts}]->(dst)
FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | CREATE (h)-[:ABOUT {ts: $ts}]->(i))
RETURN h.id, i.id
"""

# Atomic claim: match open AND set claimed in the same statement
CLAIM = """
MATCH (h:Handoff {status: 'open'})-[:TO]->(:Agent {id: $agent})
WITH h ORDER BY h.ts LIMIT 1
SET h.status = 'claimed', h.claimed_by = $agent, h.claimed_ts = $ts
WITH h
OPTIONAL MATCH (h)-[:ABOUT]->(i:Incident)
OPTIONAL MATCH (i)-[:AFFECTED]->(s:Service)
OPTIONAL MATCH (src:Agent)-[:CREATED]->(h)
RETURN h.id, h.payload, i.id, collect(DISTINCT s.id), src.id
"""

COMPLETE = """
MATCH (h:Handoff {id: $id, status: 'claimed', claimed_by: $agent})
SET h.status = 'done', h.done_ts = $ts, h.result = $result
RETURN h.id
"""

LIST = """
MATCH (src:Agent)-[:CREATED]->(h:Handoff)-[:TO]->(dst:Agent)
OPTIONAL MATCH (h)-[:ABOUT]->(i:Incident)
RETURN h.id, h.ts, h.status, h.payload, src.id, dst.id, i.id, h.claimed_by, h.result
ORDER BY h.ts DESC
LIMIT $limit
"""


def other(agent: str) -> str:
    return AGENTS[1] if agent == AGENTS[0] else AGENTS[0]


def create_handoff(graph: Graph, from_agent: str, incident: str | None, summary: str, request: str) -> dict:
    hid, ts = new_id("handoff"), now()
    payload = json.dumps({"summary": summary, "request": request})  # maps cannot be stored as properties
    rows = graph.query(CREATE, {"from": from_agent, "to": other(from_agent), "incident": incident or "",
                                "id": hid, "ts": ts, "payload": payload}).result_set
    if not rows:
        raise ValueError(f"unknown agent {from_agent}")
    return {"id": rows[0][0], "to": other(from_agent), "about": rows[0][1], "status": "open"}


def claim_handoff(graph: Graph, agent: str) -> dict | None:
    rows = graph.query(CLAIM, {"agent": agent, "ts": now()}).result_set
    if not rows:
        return None
    hid, payload, incident, services, src = rows[0]
    return {"id": hid, "payload": json.loads(payload), "incident": incident,
            "services": [s for s in services if s], "from": src, "claimed_by": agent}


def complete_handoff(graph: Graph, agent: str, handoff_id: str, result: str) -> bool:
    return bool(graph.query(COMPLETE, {"id": handoff_id, "agent": agent, "ts": now(), "result": result}).result_set)


def list_handoffs(graph: Graph, limit: int = 20) -> list[dict]:
    return [{"id": h, "ts": ts, "status": st, "payload": json.loads(p), "from": a, "to": b, "incident": i,
             "claimed_by": cb, "result": res}
            for h, ts, st, p, a, b, i, cb, res in graph.ro_query(LIST, {"limit": limit}).result_set]
