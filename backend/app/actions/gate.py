"""Decision gate shared by decision_trail (Track 03) and approval-gated actions (Track 01):
an action is blocked when a *current* decision governing the target service forbids it."""

GOVERNING = """
MATCH (d:Decision)-[:GOVERNS]->(s:Service {name: $service})
OPTIONAL MATCH (newer:Decision)-[:SUPERSEDES]->(d)
OPTIONAL MATCH (doc:Document)-[:EVIDENCE_FOR]->(d)
OPTIONAL MATCH (maker:Person)-[:MADE]->(d)
RETURN d.id, d.title, d.ts, d.status, d.forbids, d.rationale, s.id,
       collect(DISTINCT newer.id), collect(DISTINCT doc.id), collect(DISTINCT maker.name)
ORDER BY d.ts DESC
"""

STALE = """
MATCH (doc:Document {kind: 'runbook'})-[:MENTIONS]->(old:Decision)-[:GOVERNS]->(s:Service {name: $service})
MATCH (newer:Decision)-[:SUPERSEDES]->(old)
RETURN doc.id, doc.title, doc.ts, old.id, newer.id
"""


def current_decisions(graph, service: str) -> list[dict]:
    rows = graph.ro_query(GOVERNING, {"service": service}).result_set
    return [
        {"id": d, "title": t, "ts": ts, "status": st, "forbids": fb or [], "rationale": ra, "service": svc,
         "superseded_by": [n for n in newer if n], "sources": [x for x in docs if x], "made_by": [m for m in makers if m]}
        for d, t, ts, st, fb, ra, svc, newer, docs, makers in rows
    ]


def action_gate(decisions: list[dict], action: str) -> dict:
    """An action is blocked when a *current* decision governing the target forbids it."""
    blockers = [d["id"] for d in decisions if not d["superseded_by"] and action in d["forbids"]]
    return {"action": action, "allowed": not blockers, "blocked_by": blockers}
