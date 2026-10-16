"""Shared fixtures. DB tests load throwaway graphs (tenant_test_acme, tenant_test_beta) so
the dev graphs are never touched, and skip cleanly when FalkorDB is unreachable."""
import pytest

from backend.scripts import seed

ACME_SEED, BETA_SEED = 42, 7
TEST_TENANTS = {"acme": "test_acme", "beta": "test_beta"}


@pytest.fixture(scope="session")
def acme():
    data = seed.generate("acme", ACME_SEED)
    return data, seed.ground_truth("acme", ACME_SEED, data)


@pytest.fixture(scope="session")
def beta():
    data = seed.generate("beta", BETA_SEED)
    return data, seed.ground_truth("beta", BETA_SEED, data)


@pytest.fixture(scope="session")
def db():
    from backend.app.graph.client import ping

    if not ping():
        pytest.skip("FalkorDB not reachable (set TRIVENI_FALKORDB_* in .env)")
    from backend.app.graph.client import get_db

    return get_db()


@pytest.fixture(scope="session")
def loaded(db, acme, beta):
    """Load both test tenants once per session; delete them afterwards."""
    from backend.app.graph.tenant import get_graph

    reports = {
        "acme": seed.load(TEST_TENANTS["acme"], acme[0]),
        "beta": seed.load(TEST_TENANTS["beta"], beta[0]),
    }
    yield {
        "acme": get_graph(TEST_TENANTS["acme"]),
        "beta": get_graph(TEST_TENANTS["beta"]),
        "reports": reports,
    }
    for tenant in TEST_TENANTS.values():
        get_graph(tenant).delete()
