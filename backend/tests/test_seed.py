"""Generator tests. No database needed: these run anywhere."""
import networkx as nx
import pytest

from backend.app.graph import schema
from backend.app.graph.tenant import InvalidTenant, graph_name
from backend.scripts import seed


def test_deterministic():
    a, b = seed.generate("acme", 42), seed.generate("acme", 42)
    assert a.nodes == b.nodes and a.edges == b.edges
    assert seed.generate("acme", 43).edges != a.edges  # the seed actually matters


def test_every_node_and_edge_matches_schema(acme, beta):
    for data, _ in (acme, beta):
        for label, props in data.nodes.values():
            schema.validate_node(label, props)
        for rel, src, dst, props in data.edges:
            schema.validate_edge(rel, data.label(src), data.label(dst), props)
            assert schema.EDGE_TYPES[rel].category != schema.DERIVED  # derived edges come from projections only


def test_every_source_doc_exists(acme, beta):
    for data, _ in (acme, beta):
        missing = {p["source_doc"] for _, _, _, p in data.edges if "source_doc" in p} - set(data.ids("Document"))
        assert not missing


def test_counts_in_budget(acme, beta):
    a, b = acme[1]["counts"], beta[1]["counts"]
    assert 250 <= a["nodes"] <= 350          # MVP: ~300 nodes
    assert 900 <= a["edges_loaded"] <= 1300  # + derived projections ~1.3k total
    assert 60 <= b["nodes"] <= 100           # MVP: ~80 nodes


def test_scenario1_blast_radius_and_path(acme):
    data, gt = acme
    expected = {"svc:cart-api", "svc:orders-api", "svc:checkout-web", "svc:invoice-svc", "svc:refund-worker"}
    assert set(gt["scenario1"]["blast_radius_3"]) == expected
    assert gt["eval"]["A2"] == ["svc:checkout-web", "svc:cart-api", "svc:orders-api", "svc:payments-api"]


def test_scenario3_orphans(acme):
    assert acme[1]["scenario3"]["orphans"] == ["svc:legacy-fax-gateway", "svc:pdf-renderer-v1"]
    data = acme[0]
    assert not [e for e in data.edges if e[0] == "ON_CALL_FOR" and e[2] == "svc:billing-batch"]


def test_scenario2_stale_runbook(acme):
    assert acme[1]["stale_runbooks"] == ["doc:rb-billing-rerun", "doc:rb-orders-retry"]


def test_scenario4_bridges_are_top_betweenness(acme):
    """Cross-check with networkx on the KNOWS projection (mirrors projections.py)."""
    g = nx.Graph()
    g.add_edges_from(seed.expertise_edges(acme[0]))
    bc = nx.betweenness_centrality(g, normalized=False)
    people = sorted((p for p in bc if p.startswith("per:")), key=lambda p: -bc[p])
    assert sorted(people[:2]) == acme[1]["scenario4"]["key_people_top2"]


@pytest.mark.parametrize("s", [1, 7, 99, 2026])
def test_scenario4_holds_for_other_seeds(s):
    data = seed.generate("acme", s)
    g = nx.Graph()
    g.add_edges_from(seed.expertise_edges(data))
    bc = nx.betweenness_centrality(g, normalized=False)
    people = sorted((p for p in bc if p.startswith("per:")), key=lambda p: -bc[p])
    assert sorted(people[:2]) == ["per:dev-malhotra", "per:priya-nair"]


def test_tenants_share_no_people_or_teams(acme, beta):
    acme_ids, beta_ids = set(acme[0].nodes), set(beta[0].nodes)
    shared = {i for i in acme_ids & beta_ids if i.startswith(("per:", "team:", "inc:", "adr:", "ep:"))}
    assert not shared
    assert "svc:payments-api" in acme_ids & beta_ids  # deliberate overlap so a leak would show


@pytest.mark.parametrize("bad", ["Acme", "a-b", "", "x" * 40, "acme) RETURN 1 //", None])
def test_invalid_tenant_names_rejected(bad):
    with pytest.raises(InvalidTenant):
        graph_name(bad)
