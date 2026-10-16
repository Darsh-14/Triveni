"""Approval-gated actions (Track 01, recorded as graph state for Track 02).

An agent can only *propose*. The proposal is checked against the graph first: if a current Decision that
GOVERNS the target service forbids this kind of action, the Action is stored as 'blocked' with a BLOCKED_BY
edge to that decision. Otherwise it is 'proposed' and waits for a person to approve or reject it. Approved
actions are executed into a simulated outbox (no real Jira/Slack/PagerDuty), and the Action node records it.
"""
import json
from pathlib import Path

from falkordb import Graph

from backend.app.memory.conversation import new_id, now
from backend.app.actions.gate import action_gate, current_decisions

KINDS = ("create_ticket", "notify_owner", "change_retry_policy", "raise_timeout", "rerun_without_reconciliation")
OUTBOX = Path(__file__).resolve().parents[3] / "data" / "outbox"

PROPOSE = """
MATCH (s:Service {id: $target})
CREATE (a:Action {id: $id, kind: $kind, status: $status, ts: $ts, args: $args, proposed_by: $agent})-[:TARGETS {ts: $ts}]->(s)
WITH a
OPTIONAL MATCH (e:Episode {id: $episode})
FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END | CREATE (a)-[:PROPOSED_IN {ts: $ts}]->(e))
WITH a
UNWIND $blockers AS did
MATCH (d:Decision {id: did})
CREATE (a)-[:BLOCKED_BY {ts: $ts}]->(d)
RETURN count(d)
"""

# status changes only from 'proposed' (blocked / decided actions cannot be approved)
DECIDE = """
MATCH (a:Action {id: $id, status: 'proposed'}), (p:Person {id: $person})
SET a.status = $status, a.decided_ts = $ts
FOREACH (_ IN CASE WHEN $status = 'approved' THEN [1] ELSE [] END | CREATE (p)-[:APPROVED {ts: $ts}]->(a))
RETURN a.id, a.kind, a.args
"""

EXECUTED = "MATCH (a:Action {id: $id, status: 'approved'}) SET a.status = 'executed', a.executed_ts = $ts, a.outbox = $file RETURN a.id"

LIST = """
MATCH (a:Action)-[:TARGETS]->(s:Service)
OPTIONAL MATCH (a)-[:BLOCKED_BY]->(d:Decision)
OPTIONAL MATCH (p:Person)-[:APPROVED]->(a)
RETURN a.id, a.kind, a.status, a.ts, a.args, a.proposed_by, s.id, collect(DISTINCT d.id), p.id, a.outbox
ORDER BY a.ts DESC
LIMIT $limit
"""

OWNER = """
MATCH (s:Service {id: $target})
OPTIONAL MATCH (t:Team)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(s) WHERE c.valid_to IS NULL
RETURN t.name, p.id, p.name
"""


def propose(graph: Graph, agent: str, kind: str, target: str, reason: str, details: dict | None = None,
            episode: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown action kind {kind!r}; one of {KINDS}")
    service = target.removeprefix("svc:")
    gate = action_gate(current_decisions(graph, service), kind)
    status = "proposed" if gate["allowed"] else "blocked"
    aid, ts = new_id("action"), now()
    args = json.dumps({"reason": reason, **(details or {})})
    graph.query(PROPOSE, {"id": aid, "kind": kind, "status": status, "ts": ts, "args": args, "agent": agent,
                          "target": f"svc:{service}", "episode": episode or "", "blockers": gate["blocked_by"]})
    return {"id": aid, "kind": kind, "target": f"svc:{service}", "status": status, "blocked_by": gate["blocked_by"]}


def decide(graph: Graph, action_id: str, person: str, approve: bool) -> dict:
    """A person approves (-> executed into the outbox) or rejects a proposed action."""
    status = "approved" if approve else "rejected"
    rows = graph.query(DECIDE, {"id": action_id, "person": person, "status": status, "ts": now()}).result_set
    if not rows:
        raise ValueError(f"{action_id} is not a proposed action (or {person} is unknown)")
    if not approve:
        return {"id": action_id, "status": "rejected"}
    _, kind, args = rows[0]
    target = graph.ro_query("MATCH (:Action {id: $id})-[:TARGETS]->(s) RETURN s.id", {"id": action_id}).result_set[0][0]
    team, oncall, oncall_name = graph.ro_query(OWNER, {"target": target}).result_set[0]
    message = {"action": action_id, "kind": kind, "target": target, "approved_by": person, "ts": now(),
               "to": {"create_ticket": f"ticket queue of team {team}", "notify_owner": f"{oncall_name} ({oncall})"}.get(kind, team),
               **json.loads(args)}
    OUTBOX.mkdir(parents=True, exist_ok=True)
    file = OUTBOX / f"{action_id.replace(':', '-')}.json"
    file.write_text(json.dumps(message, indent=2), encoding="utf-8")  # simulated delivery
    graph.query(EXECUTED, {"id": action_id, "ts": now(), "file": file.name})
    return {"id": action_id, "status": "executed", "outbox": file.name, "delivered_to": message["to"]}


def list_actions(graph: Graph, limit: int = 30) -> list[dict]:
    return [{"id": i, "kind": k, "status": st, "ts": ts, "args": json.loads(a), "proposed_by": by, "target": t,
             "blocked_by": [d for d in bl if d], "approved_by": ap, "outbox": ob}
            for i, k, st, ts, a, by, t, bl, ap, ob in graph.ro_query(LIST, {"limit": limit}).result_set]
