"""Track 02: parallel agents on two tenants: no cross-tenant reads, no double claims, consistent history."""
from backend.app.coordination.concurrency import run


def test_parallel_agents_stay_isolated_and_consistent(db):
    r = run(agents=6, ops=10, seed_value=3)
    assert r["error_count"] == 0, r["errors"]
    assert r["cross_tenant_reads"] == 0 and r["double_claims"] == 0
    for tenant, c in r["checks"].items():
        assert c["foreign_episodes"] == 0, tenant
        assert c["duplicate_seq"] == 0 and c["next_edges"] == max(0, c["messages"] - 1), tenant
        assert c["seeded_episode_present"], tenant
    assert r["handoffs_claimed"] <= sum(r["handoffs_created"].values())
