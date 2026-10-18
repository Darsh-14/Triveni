"""Deterministic layer (all tracks): names resolve against the graph or are refused, every tool states its outcome,
the rules planner works from plain phrasing, and nothing reports a fact the graph does not hold."""
import pytest

from backend.app.graph.resolve import UnknownEntity, resolve, spot
from backend.app.graph.tenant import get_graph
from backend.app.llm.providers import RulesProvider
from backend.app.tools import REGISTRY, run_tool

T = "test_acme"


@pytest.mark.parametrize("text,labels,expected,how", [
    ("payments-api", ("Service",), "svc:payments-api", "name"),
    ("Payments API", ("Service",), "svc:payments-api", "normalized"),
    ("svc:payments-api", ("Service",), "svc:payments-api", "id"),
    ("mfa service", ("Service",), "svc:mfa-service", "normalized"),
    ("Team Ledger", ("Team",), "team:ledger", "normalized"),
    ("Priya", ("Person",), "per:priya-nair", "partial_name"),
    ("priya nair", ("Person",), "per:priya-nair", "normalized"),
    ("42", ("Incident",), "inc:0042", "normalized"),
    ("ADR-019", ("Decision", "Document"), "adr:019", "normalized"),  # the decision wins over its own document
])
def test_resolve(loaded, text, labels, expected, how):
    r = resolve(get_graph(T), text, labels)
    assert (r.id, r.how) == (expected, how)


def test_near_misses_are_suggested_never_guessed(loaded):
    g = get_graph(T)
    with pytest.raises(UnknownEntity) as e:
        resolve(g, "paymnts-api", ("Service",))
    assert [s["id"] for s in e.value.suggestions] == ["svc:payments-api"] and not e.value.ambiguous
    with pytest.raises(UnknownEntity) as e:
        resolve(g, "Menon", ("Person",))  # five people share the surname: refused, not picked
    assert e.value.ambiguous and len(e.value.suggestions) > 1
    with pytest.raises(UnknownEntity):
        resolve(g, "orders-api", ("Person",))  # right name, wrong kind


ENTITY_TOOLS = sorted(n for n, t in REGISTRY.items() if t.entities and t.read_only)


@pytest.mark.parametrize("name", ENTITY_TOOLS)
def test_every_read_tool_refuses_an_unknown_entity(loaded, name):
    """An empty traversal from a misspelled name must never read like "nothing is affected"."""
    t = REGISTRY[name]
    arg, (labels, _) = next(iter(t.entities.items()))
    args = {"blast_radius": {}, "why_not": {"kind": "on_call"}, "what_if": {"scenario": "service_decommissioned"},
            "shortest_path": {"to": "svc:payments-api", "mode": "any"}}.get(name, {})
    args[arg] = ["svc:nope-api"] if arg in ("entities",) else "nope-api-zz"
    r = run_tool(T, name, args)
    assert r.outcome == "unknown_entity" and r.data["found"] is False and "Nothing else was checked" in r.explanation


def test_outcomes_are_explicit(loaded):
    assert run_tool(T, "blast_radius", {"service": "Payments API"}).outcome == "answered"
    assert run_tool(T, "why_not", {"kind": "on_call", "service": "billing-batch"}).outcome == "not_in_graph"
    assert run_tool(T, "recall", {"entities": ["svc:payments-api"]}).outcome == "from_memory"
    r = run_tool(T, "owner_of", {"service": "billing batch"})
    assert r.resolved == [{"query": "billing batch", "id": "svc:billing-batch", "name": "billing-batch",
                           "label": "Service", "how": "normalized", "argument": "service"}]


def test_describe_traces_an_incident_to_its_cause_and_sources(loaded):
    r = run_tool(T, "describe", {"entity": "incident 42"})
    caused = [f["id"] for f in r.data["current"]["caused by"]]
    assert caused == ["dep:payments-api@2.12.0"] and [f["id"] for f in r.data["current"]["resolved by"]] == ["per:priya-nair"]
    assert "doc:pm-0042" in r.sources and r.outcome == "answered"


def test_describe_marks_superseded_decisions(loaded):
    r = run_tool(T, "describe", {"entity": "billing-batch"})
    governed = {f["id"]: f["name"] for f in r.data["current"]["governed by"]}
    assert governed["adr:011"].endswith("(superseded)") and not governed["adr:023"].endswith("(superseded)")


def test_spot_finds_entities_in_plain_phrasing(loaded):
    g = get_graph(T)
    assert [e["id"] for e in spot(g, "Payments API is down; ask Priya or Team Ledger about incident 42 and ADR-019")] == [
        "svc:payments-api", "per:priya-nair", "team:ledger", "inc:0042", "adr:019"]
    assert spot(g, "hello, anyone there?") == []


@pytest.mark.parametrize("question,plan", [
    ("Payments API is down, who should I page?", ["blast_radius", "similar_incidents", "recall"]),
    ("Who owns billing batch?", ["owner_of"]),
    ("Is it safe to raise the timeout on orders-api?", ["decision_trail"]),
    ("What decisions govern orders-api?", ["decision_trail"]),
    ("Why was ADR-019 made?", ["describe"]),
    ("What caused incident 42?", ["describe"]),
    ("Have we seen inc:0042 before?", ["describe", "similar_incidents"]),
    ("How is Priya Nair connected to billing-batch?", ["shortest_path"]),
    ("Does checkout-web depend on payments-api?", ["why_not"]),
    ("What if Priya leaves?", ["what_if"]),
    ("What does Team Ledger own?", ["describe"]),
    ("What does Priya Nair work on?", ["describe"]),
    ("hello", []),
])
def test_rules_planner_uses_the_graph(loaded, question, plan):
    assert [n for n, _ in RulesProvider.plan(question, spot(get_graph(T), question))] == plan


def test_rules_planner_passes_resolved_ids(loaded):
    q = "Is it safe to raise the timeout on orders-api?"
    assert RulesProvider.plan(q, spot(get_graph(T), q)) == [
        ("decision_trail", {"service": "orders-api", "action": "raise_timeout"})]


def test_proposing_on_a_missing_service_creates_nothing(loaded):
    from backend.app.actions.actions import propose

    g = get_graph(T)
    before = g.ro_query("MATCH (a:Action) RETURN count(a)").result_set[0][0]
    with pytest.raises(ValueError):
        propose(g, "agent:triage", "create_ticket", "svc:ghost-api", "test")
    assert g.ro_query("MATCH (a:Action) RETURN count(a)").result_set[0][0] == before  # no phantom action
    r = run_tool(T, "propose_action", {"kind": "create_ticket", "target": "ghost-api", "reason": "test"})
    assert r.outcome == "unknown_entity"


def test_dependency_paths_use_current_edges_only(loaded):
    from backend.app.tools.shortest_path import MODES
    from backend.app.tools.why_not import DEPENDS

    for q in (MODES["dependency"], DEPENDS):
        assert "all(r IN relationships(p) WHERE r.valid_to IS NULL)" in q
    r = run_tool(T, "shortest_path", {"from": "checkout-web", "to": "payments-api"})
    assert r.data["found"] and r.data["includes_ended_edges"] == []


def test_rules_mode_answers_a_typo_with_suggestions(loaded):
    import anyio

    from backend.app.agents.loop import run_agent
    from backend.app.agents.triage import SYSTEM

    r = anyio.run(lambda: run_agent("Is paymnts-api down?", T, SYSTEM, persist=False, providers=[RulesProvider()]))
    assert [(s.tool, s.outcome) for s in r.steps] == [("describe", "unknown_entity")]
    assert "did you mean payments-api" in r.answer and r.verification["verdict"] == "verified" and not r.guard


def test_recent_answers_questions_that_name_no_entity(loaded):
    r = run_tool(T, "recent", {"kind": "deployments", "service": "Payments API", "limit": 3})
    assert [i["version"] for i in r.data["items"]] == ["2.14.0", "2.13.0", "2.12.0"]
    assert r.data["items"][2]["caused"] == ["inc:0042"] and "approvals are recorded only on actions" in r.explanation
    # each deploy carries its reach: services depending on the deployed one within 3 hops (the blast radius)
    blast = {a["id"] for a in run_tool(T, "blast_radius", {"service": "payments-api"}).data["affected"]}
    assert set(r.data["items"][0]["reach"]) == blast
    assert run_tool(T, "recent", {"kind": "incidents", "limit": 1}).data["items"][0]["id"] == "inc:0057"
    assert run_tool(T, "recent", {"kind": "deployments", "service": "paymnts"}).outcome == "unknown_entity"


@pytest.mark.parametrize("question,plan", [
    ("Who approved the most recent change?", [("recent", {"kind": "actions"}), ("recent", {"kind": "deployments"})]),
    ("What was the last deploy on payments api?", [("recent", {"kind": "deployments", "service": "payments-api"})]),
    ("Latest incident on orders-api?", [("recent", {"kind": "incidents", "service": "orders-api"})]),
    ("What is waiting for approval?", [("recent", {"kind": "actions"})]),
    ("Show open handoffs", [("list_handoffs", {"status": "open"})]),
])
def test_rules_planner_handles_recency_and_approvals(loaded, question, plan):
    assert RulesProvider.plan(question, spot(get_graph(T), question)) == plan


def test_rules_planner_keeps_last_time_as_memory(loaded):
    q = "What did we learn last time payments-api failed?"
    assert [n for n, _ in RulesProvider.plan(q, spot(get_graph(T), q))] == ["blast_radius", "similar_incidents", "recall"]


def test_failed_models_cool_down_and_are_skipped(monkeypatch):
    from backend.app.llm import providers as pv

    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("TRIVENI_LLM_PROVIDERS", "groq,rules")
    monkeypatch.setenv("TRIVENI_GROQ_MODELS", "m1,m2")
    monkeypatch.setattr(pv, "_cooling", {})
    assert [p.model for p in pv.make_chain(0)] == ["m1", "m2", "rules"]  # every free-tier model gets a turn
    pv.cool_down(pv.make_chain(0)[0], "groq: RateLimitError (m1): Error code: 429 - tokens per day")
    assert [p.model for p in pv.make_chain(0)] == ["m2", "rules"]  # m1 skipped instead of failing again


def test_find_services_filters_on_current_edges(loaded):
    r = run_tool(T, "find_services", {"lang": "kotlin", "team": "Ledger", "has_on_call": False})
    assert [s["id"] for s in r.data["services"]] == ["svc:billing-batch"]  # seed: Ledger owns it, nobody on call
    assert r.data["services"][0]["owners"] == ["team:ledger"] and r.data["services"][0]["on_call"] == []
    orphans = {s["id"] for s in run_tool(T, "find_services", {"has_owner": False}).data["services"]}
    assert orphans == {"svc:pdf-renderer-v1", "svc:legacy-fax-gateway"}
    assert run_tool(T, "find_services", {"team": "Ledgr"}).outcome == "unknown_entity"


@pytest.mark.parametrize("question,plan", [
    ("Which tier-1 services have nobody on call?", [("find_services", {"tier": 1, "has_on_call": False})]),
    ("kotlin services owned by Team Ledger", [("find_services", {"lang": "kotlin", "team": "team:ledger"})]),
    ("Which python services have no owner?", [("find_services", {"lang": "python", "has_owner": False})]),
    ("Which services have no owner?", [("find_orphans", {})]),
])
def test_rules_planner_filters_services(loaded, question, plan):
    assert RulesProvider.plan(question, spot(get_graph(T), question)) == plan
