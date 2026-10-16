"""Change impact on ingest (Scenario 7 extended): a changed fact reports stale runbooks, constraints and memory to
review, and proposes an approval-gated notify_owner action. Its own tenant, because it writes."""
import pytest

from backend.app.ingest.extract import Entity, Extraction, Fact
from backend.app.ingest.pipeline import ingest
from backend.scripts import seed

T = "test_impact"
MOVE = "data/raw/live/chat-billing-move.md"


@pytest.fixture(scope="module")
def graph(db):
    from backend.app.graph.tenant import get_graph

    seed.load(T, seed.generate("acme", 42))
    yield get_graph(T)
    get_graph(T).delete()


def move() -> Extraction:
    return Extraction(
        entities=[Entity(ref="team:atlas", label="Team", name="Atlas"),
                  Entity(ref="svc:billing-batch", label="Service", name="billing-batch"),
                  Entity(ref="per:farhan-qureshi", label="Person", name="Farhan Qureshi")],
        facts=[Fact(type="OWNS", src="team:atlas", dst="svc:billing-batch", evidence="moves to Team Atlas"),
               Fact(type="ON_CALL_FOR", src="per:farhan-qureshi", dst="svc:billing-batch", evidence="I'll be on call")],
    )


def test_ownership_change_reports_its_impact(graph):
    from backend.app.memory.remember import remember

    remember(graph, "agent:triage", "billing-batch rerun failed last month", "resolved", ["svc:billing-batch"],
             procedure={"name": "Rerun billing-batch", "steps": []}, procedure_result="success")
    impact = ingest(T, MOVE, extraction=move())["impact"]
    assert sorted(impact["changes"]) == ["ON_CALL_FOR:per:farhan-qureshi->svc:billing-batch", "OWNS:team:atlas->svc:billing-batch"]
    [i] = impact["impacts"]
    assert i["service"] == "svc:billing-batch" and i["owner_now"] == "team:atlas" and i["on_call_now"] == "per:farhan-qureshi"
    assert [r["document"] for r in i["stale_runbooks"]] == ["doc:rb-billing-rerun"]  # cites superseded adr:011
    assert any(c["decision"] == "adr:023" and "rerun_without_reconciliation" in c["forbids"] for c in i["constraints"])
    assert [p["name"] for p in i["memory_to_review"]["procedures"]] == ["Rerun billing-batch"]  # Track 02 memory flagged
    [a] = impact["proposed_actions"]
    assert a["kind"] == "notify_owner" and a["status"] == "proposed"  # Track 01: waits for a human
    row = graph.ro_query("MATCH (a:Action {id: $id}) RETURN a.proposed_by, a.args", {"id": a["id"]}).result_set[0]
    assert row[0] == "system:ingest" and "doc:rb-billing-rerun" in row[1] and "adr:023" in row[1]


def test_reingesting_the_same_document_triggers_nothing(graph):
    impact = ingest(T, MOVE, extraction=move())["impact"]
    assert impact == {"changes": [], "impacts": [], "proposed_actions": []}
