"""Track 02 memory: conversation history, episodes/lessons/procedures, recall through shared entities.
Runs on its own fresh tenant because it writes."""
import json
import subprocess
import sys
from types import SimpleNamespace as NS

import anyio
import pytest

from backend.app.agents.loop import run_agent
from backend.app.agents.triage import SYSTEM
from backend.app.llm.providers import OpenAICompatProvider
from backend.app.memory.conversation import append_message, load_history, start_conversation
from backend.app.tools import run_tool
from backend.scripts import seed

T = "test_memory"


@pytest.fixture(scope="module")
def graph(db):
    from backend.app.graph.tenant import get_graph

    seed.load(T, seed.generate("acme", 42))
    yield get_graph(T)
    get_graph(T).delete()


def rows(graph, q, **p):
    return graph.ro_query(q, p).result_set


# ---------------------------------------------------------------- conversation history
def test_history_is_a_next_chain(graph):
    cid = start_conversation(graph, "user:test")
    for role, text in [("user", "payments-api is down"), ("assistant", "Page Arjun."), ("user", "and then?")]:
        append_message(graph, cid, role, text)
    assert [m["text"] for m in load_history(graph, cid)] == ["payments-api is down", "Page Arjun.", "and then?"]
    assert rows(graph, "MATCH (:Conversation {id: $c})-[:HAS_MESSAGE]->(a)-[:NEXT]->(b) RETURN a.seq, b.seq ORDER BY a.seq",
                c=cid) == [[0, 1], [1, 2]]


def test_history_survives_a_restart(graph):
    """Write in this process, read in a brand-new Python process: no state lives in memory."""
    cid = start_conversation(graph, "user:restart")
    append_message(graph, cid, "user", "remember this across restarts")
    code = ("import json; from backend.app.graph.tenant import get_graph; from backend.app.memory.conversation import load_history; "
            f"print(json.dumps(load_history(get_graph('{T}'), '{cid}')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True).stdout
    assert json.loads(out.strip().splitlines()[-1])[0]["text"] == "remember this across restarts"


def test_seeded_conversation_restores(graph):
    r = run_tool(T, "load_history", {"conversation_id": "conv:0001"})
    assert len(r.data["messages"]) == 4 and r.data["messages"][0]["role"] == "user"


# ---------------------------------------------------------------- recall + remember (scenario 5)
def test_recall_new_incident_reaches_past_episode_through_service(graph):
    graph.query("CREATE (:Incident {id: 'inc:0099', title: 'payments-api timeouts again', severity: 'SEV1', "
                "ts_open: '2026-10-16T08:00:00Z', summary: 'new'})")
    graph.query("MATCH (i:Incident {id: 'inc:0099'}), (s:Service {id: 'svc:payments-api'}) "
                "CREATE (i)-[:AFFECTED {source_doc: 'doc:test'}]->(s)")
    r = run_tool(T, "recall", {"entities": ["inc:0099"]})
    ep = r.data["episodes"][0]
    assert ep["id"] == "ep:0001" and "svc:payments-api" in ep["shared"]  # reached via the shared service, not text
    assert ep["procedures"][0]["name"] == "Roll back payments-api" and ep["procedures"][0]["success_count"] == 2
    assert ep["lessons"][0]["id"] == "lesson:pool-exhaustion"
    assert "INVOLVED:ep:0001->svc:payments-api" in {e for p in r.paths for e in p["edges"]}


def test_remember_updates_procedure_counters_and_reinforces_lesson(graph):
    r = run_tool(T, "remember", {
        "question": "payments-api timeouts again", "outcome": "resolved", "involved": ["inc:0099", "svc:payments-api"],
        "lesson": "Lowering the payments-api pool size causes connection exhaustion under checkout load; check pool config in the last deploy first.",
        "procedure_name": "Roll back payments-api", "procedure_result": "success"}, agent="agent:triage")
    assert r.data["procedure"] == {"id": "proc:rollback-payments", "success_count": 3, "fail_count": 0}
    assert r.data["lesson"] == {"id": "lesson:pool-exhaustion", "confidence": 0.9}  # reinforced, not duplicated
    assert rows(graph, "MATCH (l:Lesson) RETURN count(l)") == [[1]]
    assert rows(graph, "MATCH (:Agent {id: 'agent:triage'})-[:RAN]->(e:Episode {id: $e})-[:INVOLVED]->(x) RETURN count(x)",
                e=r.data["episode"]) == [[2]]


def test_failed_procedure_counts(graph):
    r = run_tool(T, "remember", {"question": "x", "outcome": "escalated", "involved": ["svc:payments-api"],
                                 "procedure_name": "Roll back payments-api", "procedure_result": "fail"}, agent="agent:remediation")
    assert r.data["procedure"]["fail_count"] == 1
    assert rows(graph, "MATCH (:Agent {id: 'agent:remediation'})-[:RAN]->(e:Episode {id: $e}) RETURN count(e)",
                e=r.data["episode"]) == [[1]]


def test_model_cannot_choose_agent_or_tenant(graph):
    with pytest.raises(ValueError):
        run_tool(T, "remember", {"question": "x", "outcome": "answered", "involved": [], "agent": "agent:remediation"})


def test_recall_is_tenant_isolated(graph, loaded):
    beta = run_tool("test_beta", "recall", {"entities": ["svc:payments-api"]}).data["episodes"]
    assert [e["id"] for e in beta] == ["ep:b0001"]


# ---------------------------------------------------------------- agent: history in, conversation + episode out
class Scripted:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        return self.responses.pop(0)


def _oa(content="", calls=()):
    tcs = [NS(id=i, type="function", function=NS(name=n, arguments=a)) for i, n, a in calls] or None
    return NS(model="scripted", choices=[NS(message=NS(content=content, tool_calls=tcs))])


def test_agent_persists_conversation_and_episode_and_reloads_history(graph):
    first = Scripted([_oa("", [("c1", "owner_of", '{"service": "billing-batch"}')]), _oa("Ledger owns billing-batch.")])
    r1 = anyio.run(lambda: run_agent("Who owns billing-batch?", T, SYSTEM,
                                     providers=[OpenAICompatProvider("groq", client=first, model="m")]))
    assert r1.conversation_id.startswith("conv:") and r1.episode.startswith("ep:")
    assert rows(graph, "MATCH (e:Episode {id: $e})-[:INVOLVED]->(x) RETURN collect(x.id)", e=r1.episode)[0][0]
    assert [m["text"] for m in load_history(graph, r1.conversation_id)] == ["Who owns billing-batch?", "Ledger owns billing-batch."]

    second = Scripted([_oa("Still Ledger.")])
    r2 = anyio.run(lambda: run_agent("And who is on call?", T, SYSTEM, conversation_id=r1.conversation_id,
                                     providers=[OpenAICompatProvider("groq", client=second, model="m")]))
    sent = [m["content"] for m in second.requests[0]["messages"] if m["role"] in ("user", "assistant")]
    assert sent == ["Who owns billing-batch?", "Ledger owns billing-batch.", "And who is on call?"]  # history from the graph
    assert r2.conversation_id == r1.conversation_id and len(load_history(graph, r1.conversation_id)) == 4


# ---------------------------------------------------------------- decay (P1)
def test_lessons_decay_with_age_on_read(graph):
    from datetime import datetime, timedelta, timezone

    from backend.app.memory.recall import HALF_LIFE_DAYS, recall

    reinforced = rows(graph, "MATCH (l:Lesson {id: 'lesson:pool-exhaustion'}) RETURN l.last_reinforced")[0][0]
    seeded = datetime.strptime(reinforced, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)  # as stored, whatever ran before
    fresh = recall(graph, ["svc:payments-api"], now=seeded)
    later = recall(graph, ["svc:payments-api"], now=seeded + timedelta(days=HALF_LIFE_DAYS))
    much_later = recall(graph, ["svc:payments-api"], now=seeded + timedelta(days=4 * HALF_LIFE_DAYS))

    def lesson(r):
        return next(x for ep in r["episodes"] for x in ep["lessons"] if x["id"] == "lesson:pool-exhaustion")

    stored = lesson(fresh)["confidence"]
    assert lesson(fresh)["effective_confidence"] == round(stored, 2)
    assert lesson(later)["effective_confidence"] == round(stored * 0.5, 2)  # one half-life
    assert lesson(much_later)["faded"] is True  # still returned, flagged, never deleted
    assert lesson(much_later)["confidence"] == stored  # the stored value is not rewritten by reading


def test_recent_episodes_rank_first_when_sharing_the_same_entities(graph):
    from backend.app.memory.recall import recall
    from backend.app.memory.remember import remember

    old = remember(graph, "agent:triage", "decay-old", "answered", ["svc:fraud-scorer"])["episode"]
    graph.query("MATCH (e:Episode {id: $e}) SET e.ts = '2025-01-01T00:00:00Z'", {"e": old})
    new = remember(graph, "agent:triage", "decay-new", "answered", ["svc:fraud-scorer"])["episode"]
    ranked = [e["id"] for e in recall(graph, ["svc:fraud-scorer"])["episodes"]]
    assert ranked.index(new) < ranked.index(old)


def test_failed_procedure_weakens_lessons_learned_with_it(graph):
    from backend.app.memory.remember import remember

    first = remember(graph, "agent:triage", "cache flush", "resolved", ["svc:config-svc"],
                     lesson="Flushing the config cache fixes stale flags.",
                     procedure={"name": "Flush config cache", "steps": []}, procedure_result="success")
    before = first["lesson"]["confidence"]
    failed = remember(graph, "agent:triage", "cache flush again", "escalated", ["svc:config-svc"],
                      procedure={"name": "Flush config cache", "steps": []}, procedure_result="fail")
    weakened = {x["id"]: x["confidence"] for x in failed["weakened_lessons"]}
    assert weakened[first["lesson"]["id"]] == round(before - 0.15, 2)
