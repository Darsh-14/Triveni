"""The demo approvals inbox: the graph decides which actions are blocked; the rest can be approved or rejected.
Its own tenant, because it deletes and writes actions."""
import pytest

from backend.app.actions.actions import decide, list_actions
from backend.app.graph.tenant import get_graph
from backend.scripts import demo_actions, seed

T = "test_demo_actions"


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def graph(db, monkeypatch_module):
    """The demo state: seed plus the base documents demo_reset ingests (ADR-041 comes from one of them)."""
    import glob

    from backend.app.ingest.pipeline import ingest

    monkeypatch_module.setenv("DEMO_REPLAY", "1")  # cached extractions only, never a model
    seed.load(T, seed.generate("acme", 42))
    for path in sorted(glob.glob("data/raw/*.md")):
        ingest(T, path)
    yield get_graph(T)
    get_graph(T).delete()


def test_reset_gives_a_known_inbox_and_the_gate_decides(graph):
    actions = demo_actions.reset(T)
    blocked = {(a["kind"], a["target"]): a["blocked_by"] for a in actions if a["status"] == "blocked"}
    assert blocked == {("change_retry_policy", "svc:orders-api"): ["adr:019"],
                       ("rerun_without_reconciliation", "svc:billing-batch"): ["adr:023"],
                       ("raise_timeout", "svc:search-api"): ["adr:041"]}
    assert sum(a["status"] == "proposed" for a in actions) == 5
    assert len(demo_actions.reset(T)) == len(actions)  # resetting again replaces, never piles up


def test_demo_actions_can_be_approved_or_rejected_but_blocked_ones_cannot(graph):
    actions = demo_actions.reset(T)
    pending = {a["target"]: a for a in actions if a["status"] == "proposed"}  # same ts: pick by target, not order
    done = decide(graph, pending["svc:orders-api"]["id"], "per:priya-nair", approve=True)
    assert done["status"] == "executed" and done["outbox"]
    rejected = pending["svc:payments-api"]["id"]
    assert decide(graph, rejected, "per:priya-nair", approve=False)["status"] == "rejected"
    orphan = pending["svc:pdf-renderer-v1"]["id"]
    assert "unowned" in decide(graph, orphan, "per:priya-nair", approve=True)["delivered_to"]  # never "None"
    with pytest.raises(ValueError):
        decide(graph, next(a["id"] for a in actions if a["status"] == "blocked"), "per:priya-nair", approve=True)
    statuses = {a["id"]: a["status"] for a in list_actions(graph)}
    assert statuses[rejected] == "rejected"
