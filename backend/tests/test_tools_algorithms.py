"""Algorithm tools (Track 01) on the pristine seeded tenant, checked against ground truth computed independently
(pure-Python PageRank, networkx betweenness, Python orphan check)."""
from backend.app.tools import run_tool

T = "test_acme"


def test_critical_services_pagerank_matches_ground_truth(loaded, acme):
    r = run_tool(T, "critical_services", {"limit": 3})
    assert [s["id"] for s in r.data["services"]] == acme[1]["eval"]["A3"]
    assert r.data["ended_dependencies"] == 0
    top = r.data["services"][0]
    assert top["dependents"] and all(p["edges"][0].endswith("->" + top["id"]) for p in r.paths if p["nodes"][1] == top["id"]
                                     and p["edges"][0].startswith("DEPENDS_ON"))


def test_key_people_scenario4(loaded, acme):
    r = run_tool(T, "key_people", {"limit": 5})
    top2 = sorted(p["id"] for p in r.data["people"][:2])
    assert top2 == acme[1]["scenario4"]["key_people_top2"]  # same set as networkx on the same projection
    priya = next(p for p in r.data["people"] if p["id"] == "per:priya-nair")
    assert set(priya["teams_spanned"]) == {"Payments", "Ledger"}  # why she is a bridge
    assert r.data["samples"] >= 2000 and r.params["seed"] == 42


def test_key_people_is_deterministic(loaded):
    a = run_tool(T, "key_people", {}).data["people"]
    b = run_tool(T, "key_people", {}).data["people"]
    assert [(p["id"], p["score"]) for p in a] == [(p["id"], p["score"]) for p in b]


def test_find_orphans_scenario3(loaded, acme):
    r = run_tool(T, "find_orphans", {})
    assert sorted(o["id"] for o in r.data["orphans"]) == acme[1]["scenario3"]["orphans"]
    for o in r.data["orphans"]:
        expected = sorted(s for rel, s, d, p in acme[0].edges if rel == "DEPENDS_ON" and d == o["id"])
        assert o["dependents"] == expected and o["former_owners"] == []
