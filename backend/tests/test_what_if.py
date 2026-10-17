"""what_if: counterfactuals on a GRAPH.COPY sandbox; the real tenant graph must never change."""
import pytest

from backend.app.graph.tenant import get_graph, list_tenants
from backend.app.tools import run_tool

T = "test_acme"


def counts(graph):
    return graph.ro_query("MATCH (n) RETURN count(n)").result_set[0][0], graph.ro_query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]


def test_team_dissolved_orphans_its_uncovered_service(loaded):
    before = counts(get_graph(T))
    r = run_tool(T, "what_if", {"scenario": "team_dissolved", "entity": "team:ledger"})
    assert r.data["new_orphans"] == ["svc:billing-batch"]  # ledger owned it and nobody is on call
    assert "svc:billing-batch" in r.data["footprint"]["owns"]
    assert counts(get_graph(T)) == before  # the real graph is untouched
    assert not [t for t in list_tenants() if "__whatif" in t]  # sandbox deleted


def test_person_leaves_moves_the_single_point_of_knowledge(loaded):
    r = run_tool(T, "what_if", {"scenario": "person_leaves", "entity": "Priya Nair"})
    assert r.data["entity"] == "per:priya-nair"
    assert "per:priya-nair" in [p["id"] for p in r.data["key_people_before"]]
    assert "per:priya-nair" not in [p["id"] for p in r.data["key_people_after"]]
    assert r.data["new_key_people"]  # somebody else becomes a bridge
    assert set(r.data["footprint"]["knows"]) >= {"svc:payments-api", "svc:reconciliation-job"}
    assert all(p.get("superseded") for p in r.paths if p["edges"] and p["edges"][0].startswith("KNOWS:per:priya-nair"))


def test_service_decommissioned_lists_dependents(loaded, acme):
    r = run_tool(T, "what_if", {"scenario": "service_decommissioned", "entity": "payments-api"})
    assert sorted(d["id"] for d in r.data["footprint"]["dependents"]) == acme[1]["scenario1"]["blast_radius_3"]


def test_wrong_entity_kind_is_rejected(loaded):
    r = run_tool(T, "what_if", {"scenario": "person_leaves", "entity": "svc:payments-api"})
    assert r.outcome == "unknown_entity" and r.data["labels"] == ["Person"]  # no clone was made, nothing simulated
