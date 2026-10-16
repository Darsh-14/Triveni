"""Tenant isolation (Track 02): a query on one tenant's graph never returns another tenant's data."""
from backend.app.graph.tenant import get_graph, list_tenants

FIND_IDS = "MATCH (n) WHERE n.id IN $ids RETURN n.id"


def only_in(a, b) -> list[str]:
    return sorted(set(a.nodes) - set(b.nodes))


def test_acme_never_returns_beta_data(loaded, acme, beta):
    beta_only = only_in(beta[0], acme[0])
    assert beta_only  # the check is meaningful
    assert loaded["acme"].ro_query(FIND_IDS, {"ids": beta_only}).result_set == []


def test_beta_never_returns_acme_data(loaded, acme, beta):
    acme_only = only_in(acme[0], beta[0])
    assert loaded["beta"].ro_query(FIND_IDS, {"ids": acme_only}).result_set == []


def test_same_service_id_resolves_per_tenant(loaded):
    q = """MATCH (t:Team)-[r:OWNS]->(:Service {id: 'svc:payments-api'}) WHERE r.valid_to IS NULL RETURN t.id"""
    assert loaded["acme"].ro_query(q).result_set == [["team:payments"]]
    assert loaded["beta"].ro_query(q).result_set == [["team:core"]]


def test_whole_graph_scan_stays_in_tenant(loaded, acme, beta):
    acme_ids = {r[0] for r in loaded["acme"].ro_query("MATCH (n) RETURN n.id").result_set}
    beta_ids = {r[0] for r in loaded["beta"].ro_query("MATCH (n) RETURN n.id").result_set}
    assert acme_ids == set(acme[0].nodes)
    assert beta_ids == set(beta[0].nodes)


def test_tenants_are_separate_graphs(loaded):
    assert {"test_acme", "test_beta"} <= set(list_tenants())
    assert get_graph("test_acme").name != get_graph("test_beta").name
