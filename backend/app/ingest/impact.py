"""Change impact (Track 03 -> Track 02 -> Track 01): when an ingested document changes a fact, say what that touches.

For each service whose ownership, on-call or dependencies changed:
  - runbooks that now cite a superseded decision (stale)          Track 03 knowledge currency
  - current decisions that constrain it (what the new owner must respect)
  - memory about it worth reviewing: episodes and procedures      Track 02
  - who owns it / is on call now
and propose a notify_owner action (approval-gated) so the new owner hears about it   Track 01
Only facts that actually changed (created or ended) count, so re-ingesting a document triggers nothing.
"""
from falkordb import Graph

from backend.app.actions.actions import propose
from backend.app.actions.gate import STALE, current_decisions, is_current

CHANGE_TYPES = {"OWNS", "ON_CALL_FOR", "DEPENDS_ON"}

MEMORY = """
MATCH (s:Service {id: $svc})
OPTIONAL MATCH (e:Episode)-[:INVOLVED]->(s)
OPTIONAL MATCH (p:Procedure)-[:FOR]->(s)
RETURN s.name, collect(DISTINCT {id: e.id, question: e.question, ts: e.ts}), collect(DISTINCT {id: p.id, name: p.name})
"""

NOW = """
MATCH (s:Service {id: $svc})
OPTIONAL MATCH (t:Team)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(s) WHERE c.valid_to IS NULL
RETURN t.id, t.name, p.id, p.name
"""


def _service_of(fact: str) -> list[str]:
    rel, _, ends = fact.partition(":")
    src, _, dst = ends.partition("->")
    return [x for x in ((src, dst) if rel == "DEPENDS_ON" else (dst,)) if x.startswith("svc:")]


def change_impact(graph: Graph, report: dict) -> dict:
    changes = [f for f in report["facts"]
               if f["action"] in ("created", "ended") and f["fact"].split(":")[0] in CHANGE_TYPES]
    services = sorted({s for f in changes for s in _service_of(f["fact"])})
    impacts, actions = [], []
    for svc in services:
        name, episodes, procedures = graph.ro_query(MEMORY, {"svc": svc}).result_set[0]
        team_id, team, person_id, person = graph.ro_query(NOW, {"svc": svc}).result_set[0]
        stale = [{"document": d, "title": t, "cites": old, "superseded_by": new}
                 for d, t, _, old, new in graph.ro_query(STALE, {"service": name}).result_set]
        constraints = [{"decision": d["id"], "title": d["title"], "forbids": d["forbids"], "sources": d["sources"]}
                       for d in current_decisions(graph, name) if is_current(d)]
        what = [f["fact"] for f in changes if svc in _service_of(f["fact"])]
        impact = {
            "service": svc, "changed": what, "owner_now": team_id, "on_call_now": person_id,
            "stale_runbooks": stale, "constraints": constraints,
            "memory_to_review": {"episodes": [e for e in episodes if e["id"]], "procedures": [p for p in procedures if p["id"]]},
        }
        impacts.append(impact)
        if any(f.startswith(("OWNS:", "ON_CALL_FOR:")) for f in what):
            reason = (f"{name} changed per {report['document']}: now owned by {team or 'nobody'}, on call {person or 'nobody'}. "
                      + (f"Stale runbooks: {', '.join(s['document'] for s in stale)}. " if stale else "")
                      + (f"Constraints: {'; '.join(c['decision'] + ' forbids ' + ', '.join(c['forbids']) for c in constraints if c['forbids'])}. "
                         if any(c["forbids"] for c in constraints) else "")
                      + (f"{len(impact['memory_to_review']['episodes'])} past episode(s) to review." if impact['memory_to_review']['episodes'] else ""))
            actions.append(propose(graph, "system:ingest", "notify_owner", svc, reason.strip(),
                                   {"title": f"Handover brief: {name}", "source_doc": report["document"]}))
    return {"changes": [f["fact"] for f in changes], "impacts": impacts, "proposed_actions": actions}
