"""Eval scoring (no model) and the two tools the eval exposed as missing: list_handoffs, team_services."""
from backend.app.coordination.handoff import create_handoff
from backend.app.tools import run_tool
from backend.scripts import eval as ev

NAMES = {"svc:orders-api": "svc:orders-api", "orders-api": "svc:orders-api", "priya nair": "per:priya-nair",
         "team atlas": "team:atlas", "atlas": "team:atlas", "adr-019": "adr:019", "adr:019": "adr:019"}


def test_entities_line_is_normalised_to_ids():
    answer = "Blocked.\n\nENTITIES: `orders-api`, Priya Nair, Team Atlas, ADR-019, ADR 7"
    assert ev.entities(answer, NAMES) == {"svc:orders-api", "per:priya-nair", "team:atlas", "adr:019", "adr:007"}


def test_missing_or_unknown_entities_count_as_wrong():
    assert ev.entities("no entities line here", NAMES) == set()
    assert ev.entities("ENTITIES: orders-api, insufficient information", NAMES) == {"svc:orders-api", "insufficient information"}


def test_every_question_has_ground_truth_and_one_track():
    ids = [q.id for q in ev.QUESTIONS]
    assert len(ids) == 15 and len(set(ids)) == 15
    assert {q.track for q in ev.QUESTIONS} == {"01", "02", "03"}
    assert all(sum(q.track == t for q in ev.QUESTIONS) == 5 for t in ("01", "02", "03"))


def test_list_handoffs_tool(loaded, acme):
    from backend.app.graph.tenant import get_graph

    h = create_handoff(get_graph("test_acme"), "agent:triage", "inc:0057", "tool test", "check")
    r = run_tool("test_acme", "list_handoffs", {"status": "open"})
    assert h["id"] in [x["id"] for x in r.data["handoffs"]]
    assert f"ABOUT:{h['id']}->inc:0057" in {e for p in r.paths for e in p["edges"]}
    get_graph("test_acme").query("MATCH (x:Handoff {id: $id}) DETACH DELETE x", {"id": h["id"]})  # keep the shared tenant pristine


def test_team_services_with_stale_runbooks(loaded):
    r = run_tool("test_acme", "team_services", {"team": "Ledger"})
    assert r.data["team"] == "team:ledger"
    assert "svc:billing-batch" in [s["id"] for s in r.data["services"]]
    assert r.data["stale_runbooks"] == ["doc:rb-billing-rerun"]  # cites adr:011, superseded by adr:023
    assert run_tool("test_acme", "team_services", {"team": "team:atlas"}).data["stale_runbooks"] == []  # before the move


def test_scoring_rule_allows_only_restated_question_entities():
    expected, asked = {"adr:019"}, {"svc:orders-api"}
    assert ev.is_correct({"adr:019"}, expected, asked, "No, blocked", r"\bno\b")
    assert ev.is_correct({"adr:019", "svc:orders-api"}, expected, asked, "No, blocked", r"\bno\b")  # restates the subject
    assert not ev.is_correct({"adr:019", "svc:payments-api"}, expected, asked, "No", "")  # a real extra is wrong
    assert not ev.is_correct({"svc:orders-api"}, expected, asked, "No", "")  # missing the answer is wrong
    assert not ev.is_correct({"adr:019"}, expected, asked, "Yes, go ahead", r"\b(no|not|blocked)\b")  # must-pattern
