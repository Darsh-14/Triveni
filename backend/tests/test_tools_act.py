"""Track 01 traversal tools against seed ground truth."""
import pytest

from backend.app.tools import run_tool

T = "test_acme"


def test_blast_radius_scenario1(loaded, acme):
    gt = acme[1]["scenario1"]
    r = run_tool(T, "blast_radius", {"service": "payments-api"})
    assert sorted(a["id"] for a in r.data["affected"]) == gt["blast_radius_3"]
    assert r.data["service"]["on_call"] == gt["on_call"] and r.data["service"]["team"] == gt["owner_team"]
    hops = {a["id"]: a["hops"] for a in r.data["affected"]}
    assert hops["svc:orders-api"] == 1 and hops["svc:cart-api"] == 2 and hops["svc:checkout-web"] == 3
    assert all(a["team"] for a in r.data["affected"])  # every affected service has a current owner to contact
    assert "DEPENDS_ON:svc:orders-api->svc:payments-api" in {e for p in r.paths for e in p["edges"]}


def test_blast_radius_depth_is_validated(loaded):
    assert len(run_tool(T, "blast_radius", {"service": "payments-api", "depth": 1}).data["affected"]) == 2
    with pytest.raises(ValueError):
        run_tool(T, "blast_radius", {"service": "payments-api", "depth": 9})


def test_shortest_dependency_path(loaded, acme):
    r = run_tool(T, "shortest_path", {"from": "checkout-web", "to": "payments-api"})
    assert r.data["nodes"] == acme[1]["eval"]["A2"] and r.data["hops"] == 3
    assert run_tool(T, "shortest_path", {"from": "payments-api", "to": "checkout-web"}).data["found"] is False


def test_shortest_any_path_crosses_entity_types(loaded):
    r = run_tool(T, "shortest_path", {"from": "per:priya-nair", "to": "svc:reconciliation-job", "mode": "any"})
    assert r.data["found"] and r.data["nodes"][0] == "per:priya-nair" and r.data["hops"] == 2
    assert r.data["edges"][0].startswith("RESOLVED:per:priya-nair->inc:")
