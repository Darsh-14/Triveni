"""Track 02 coordination + Track 01 actions (Scenarios 2 and 6): agents share state only through Handoff and Action
nodes in the tenant graph; actions are gated by decisions and need a human approval."""
import json
import threading
from types import SimpleNamespace as NS

import anyio
import pytest
from fastapi.testclient import TestClient

from backend.app.actions.actions import OUTBOX
from backend.app.agents import remediation
from backend.app.agents.loop import run_agent
from backend.app.agents.triage import SYSTEM
from backend.app.coordination.handoff import claim_handoff, create_handoff
from backend.app.llm.providers import OpenAICompatProvider, RulesProvider
from backend.app.main import app
from backend.scripts import seed

T = "test_coord"


@pytest.fixture(scope="module")
def graph(db):
    from backend.app.graph.tenant import get_graph

    seed.load(T, seed.generate("acme", 42))
    yield get_graph(T)
    get_graph(T).delete()


def rows(graph, q, **p):
    return graph.ro_query(q, p).result_set


class Scripted:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        return self.responses.pop(0)


def _oa(content="", calls=()):
    tcs = [NS(id=i, type="function", function=NS(name=n, arguments=json.dumps(a))) for i, n, a in calls] or None
    return NS(model="scripted", choices=[NS(message=NS(content=content, tool_calls=tcs))])


def test_claim_is_atomic_under_concurrency(graph):
    h = create_handoff(graph, "agent:triage", "inc:0057", "race test", "claim me")
    wins = []

    def claimer():
        from backend.app.graph.tenant import get_graph
        r = claim_handoff(get_graph(T), "agent:remediation")
        wins.append(r["id"] if r else None)

    threads = [threading.Thread(target=claimer) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert wins.count(h["id"]) == 1 and wins.count(None) == 7


def test_triage_hands_off_over_mcp(graph):
    script = Scripted([_oa("", [("c1", "handoff", {"incident": "inc:0057", "summary": "orders-api p99 > 4s, workers saturated",
                                                   "request": "Propose a fix and a follow-up ticket"})]),
                       _oa("Handed off to remediation.")])
    r = anyio.run(lambda: run_agent("inc:0057 needs a fix, hand it off", T, SYSTEM, persist=False,
                                    providers=[OpenAICompatProvider("groq", client=script, model="m")]))
    assert r.steps[0].tool == "handoff" and r.steps[0].via == "mcp"
    assert rows(graph, """MATCH (:Agent {id: 'agent:triage'})-[:CREATED]->(h:Handoff {status: 'open'})-[:TO]->(:Agent {id: 'agent:remediation'})
                          MATCH (h)-[:ABOUT]->(i:Incident) RETURN i.id""") == [["inc:0057"]]


def test_remediation_claims_proposes_and_completes(graph):
    script = Scripted([
        _oa("Check decisions first.", [("r1", "decision_trail", {"service": "orders-api", "action": "change_retry_policy"}),
                                       ("r2", "propose_action", {"kind": "change_retry_policy", "target": "orders-api",
                                                                 "reason": "retries mask saturation"}),
                                       ("r3", "propose_action", {"kind": "create_ticket", "target": "orders-api",
                                                                 "reason": "autoscale workers on queue depth [doc:pm-0057]",
                                                                 "title": "Autoscale orders-api workers"})]),
        _oa("Retry change is blocked by adr:019; proposed an autoscaling ticket instead."),
    ])
    handoff, result = anyio.run(lambda: remediation.run_once(T, providers=[OpenAICompatProvider("gemini", client=script, model="m")]))
    assert handoff["incident"] == "inc:0057" and handoff["claimed_by"] == "agent:remediation"
    assert [s.tool for s in result.steps] == ["decision_trail", "propose_action", "propose_action"]
    assert rows(graph, "MATCH (h:Handoff {id: $id}) RETURN h.status, h.claimed_by", id=handoff["id"]) == [["done", "agent:remediation"]]
    blocked = rows(graph, "MATCH (a:Action {kind: 'change_retry_policy'})-[:BLOCKED_BY]->(d:Decision) RETURN a.status, d.id, a.proposed_by")
    assert blocked == [["blocked", "adr:019", "agent:remediation"]]  # graph-gated action (Scenario 2)
    assert rows(graph, "MATCH (a:Action {kind: 'create_ticket'})-[:TARGETS]->(s) RETURN a.status, s.id") == [["proposed", "svc:orders-api"]]
    assert rows(graph, "MATCH (:Agent {id: 'agent:remediation'})-[:RAN]->(e:Episode) RETURN count(e)")[0][0] >= 1


def test_human_approves_ticket_via_api(graph):
    client = TestClient(app)
    action = next(a for a in client.get("/api/actions", params={"tenant": T}).json() if a["kind"] == "create_ticket")
    r = client.post(f"/api/actions/{action['id']}/decide", json={"tenant": T, "person": "per:meera-pillai", "approve": True}).json()
    assert r["status"] == "executed" and r["delivered_to"] == "ticket queue of team Orders"
    assert json.loads((OUTBOX / r["outbox"]).read_text())["title"] == "Autoscale orders-api workers"
    assert rows(graph, "MATCH (:Person {id: 'per:meera-pillai'})-[:APPROVED]->(a:Action {id: $id}) RETURN a.status", id=action["id"]) == [["executed"]]
    again = client.post(f"/api/actions/{action['id']}/decide", json={"tenant": T, "person": "per:meera-pillai", "approve": True})
    assert again.status_code == 409  # cannot approve twice


def test_blocked_action_cannot_be_approved(graph):
    client = TestClient(app)
    blocked = next(a for a in client.get("/api/actions", params={"tenant": T}).json() if a["status"] == "blocked")
    assert blocked["blocked_by"] == ["adr:019"]
    r = client.post(f"/api/actions/{blocked['id']}/decide", json={"tenant": T, "person": "per:meera-pillai", "approve": True})
    assert r.status_code == 409


def test_reject_and_rules_remediation(graph):
    create_handoff(graph, "agent:triage", "inc:0057", "second one", "rules mode please")
    handoff, result = anyio.run(lambda: remediation.run_once(T, providers=[RulesProvider()]))
    assert [s.tool for s in result.steps] == ["recall", "decision_trail", "propose_action"]
    client = TestClient(app)
    proposed = next(a for a in client.get("/api/actions", params={"tenant": T}).json() if a["status"] == "proposed")
    r = client.post(f"/api/actions/{proposed['id']}/decide", json={"tenant": T, "person": "per:meera-pillai", "approve": False})
    assert r.json() == {"id": proposed["id"], "status": "rejected"}


def test_no_open_handoff(graph):
    assert anyio.run(lambda: remediation.run_once(T, providers=[RulesProvider()])) == (None, None)
