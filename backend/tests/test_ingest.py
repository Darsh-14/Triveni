"""Ingestion (Track 03): extraction schema, merge rules, temporal currency, source tracking.

Merge tests pass explicit Extraction fixtures (what the model would return) so they are
deterministic and need no API key. One live-LLM test runs only when ANTHROPIC_API_KEY is set.
"""
import os

import pytest
from dotenv import load_dotenv

from backend.app.ingest.extract import Entity, Extraction, Fact, read_document
from backend.app.ingest.pipeline import ingest
from backend.app.tools import run_tool
from backend.scripts import seed

load_dotenv()  # so the live-model skipif sees a key kept in .env
TENANT = "test_ingest"
BILLING_MOVE = "data/raw/live/chat-billing-move.md"


@pytest.fixture(scope="module")
def graph(db):
    """A fresh acme graph per module: ingestion mutates it, so it is kept apart from tenant_test_acme."""
    from backend.app.graph.tenant import get_graph

    seed.load(TENANT, seed.generate("acme", 42))
    yield get_graph(TENANT)
    get_graph(TENANT).delete()


def billing_move() -> Extraction:
    return Extraction(
        entities=[
            Entity(ref="team:atlas", label="Team", name="Atlas"),
            Entity(ref="team:ledger", label="Team", name="Ledger"),
            Entity(ref="svc:billing-batch", label="Service", name="billing-batch"),
            Entity(ref="per:farhan-qureshi", label="Person", name="Farhan Qureshi"),
            Entity(ref="adr:023", label="Decision", name="ADR-023"),
        ],
        facts=[
            Fact(type="OWNS", src="team:atlas", dst="svc:billing-batch", evidence="billing-batch moves from Team Ledger to Team Atlas"),
            Fact(type="ON_CALL_FOR", src="per:farhan-qureshi", dst="svc:billing-batch", evidence="I'll be on call for billing-batch"),
        ],
    )


def rows(graph, q, **p):
    return graph.ro_query(q, p).result_set


# ---------------------------------------------------------------- offline
def test_read_document_front_matter():
    d = read_document(BILLING_MOVE)
    assert (d.id, d.kind, d.ts, d.author) == ("doc:chat-billing-move", "chat", "2026-10-16T09:00:00Z", "Farhan Qureshi")
    assert "billing-batch moves" in d.text


def test_extraction_schema_only_allows_known_types():
    schema = Extraction.model_json_schema()["$defs"]
    assert set(schema["Entity"]["properties"]["label"]["enum"]) == {"Person", "Team", "Service", "Incident", "Decision"}
    allowed = set(schema["Fact"]["properties"]["type"]["enum"])
    assert "KNOWS" not in allowed and "MENTIONS" not in allowed and "OWNS" in allowed


# ---------------------------------------------------------------- scenario 7: knowledge kept current
def test_scenario7_billing_batch_moves_to_atlas(graph):
    before = run_tool(TENANT, "owner_of", {"service": "billing-batch"})
    assert [o["id"] for o in before.data["owners"]] == ["team:ledger"] and before.data["on_call"] == []

    report = ingest(TENANT, BILLING_MOVE, extraction=billing_move())
    assert {f["action"] for f in report["facts"]} == {"created"}
    assert report["facts"][0]["closed"] == ["team:ledger"]
    assert not report["rejected"]

    after = run_tool(TENANT, "owner_of", {"service": "billing-batch", "include_history": True})
    assert [o["id"] for o in after.data["owners"]] == ["team:atlas"]
    assert [p["id"] for p in after.data["on_call"]] == ["per:farhan-qureshi"]
    assert set(after.sources) == {"doc:chat-billing-move", "doc:service-catalog"}  # both sources shown
    old = [h for h in after.data["history"] if h["id"] == "team:ledger"][0]
    assert old["valid_to"] == "2026-10-16T09:00:00Z"  # history kept, not deleted


def test_old_edge_records_what_ended_it(graph):
    assert rows(graph, """MATCH (:Team {id: 'team:ledger'})-[r:OWNS]->(:Service {id: 'svc:billing-batch'})
                          RETURN r.valid_from, r.valid_to, r.source_doc, r.ended_by""") == [
        ["2026-03-01T00:00:00Z", "2026-10-16T09:00:00Z", "doc:service-catalog", "doc:chat-billing-move"]]


def test_document_linked_to_what_it_mentions(graph):
    mentioned = {r[0] for r in rows(graph, "MATCH (:Document {id: 'doc:chat-billing-move'})-[:MENTIONS]->(n) RETURN n.id")}
    assert {"team:atlas", "svc:billing-batch", "per:farhan-qureshi", "adr:023"} <= mentioned
    assert rows(graph, "MATCH (p:Person)-[:WROTE]->(:Document {id: 'doc:chat-billing-move'}) RETURN p.id") == [["per:farhan-qureshi"]]


def test_projections_refreshed_after_ingest(graph):
    assert rows(graph, "MATCH (:Team {id: 'team:atlas'})-[:RESPONSIBLE_FOR]->(:Service {id: 'svc:billing-batch'}) RETURN count(*)") == [[1]]
    assert rows(graph, "MATCH (:Team {id: 'team:ledger'})-[:RESPONSIBLE_FOR]->(:Service {id: 'svc:billing-batch'}) RETURN count(*)") == [[0]]


def test_reingest_is_idempotent(graph):
    edges_before = rows(graph, "MATCH ()-[r]->() RETURN count(r)")[0][0]
    report = ingest(TENANT, BILLING_MOVE, extraction=billing_move())
    assert {f["action"] for f in report["facts"]} == {"unchanged"}
    assert rows(graph, "MATCH ()-[r]->() RETURN count(r)")[0][0] == edges_before


# ---------------------------------------------------------------- schema enforcement
def test_invalid_facts_are_rejected_not_written(graph):
    bad = Extraction(
        entities=[Entity(ref="per:kavya-rao", label="Person", name="Kavya Rao"),
                  Entity(ref="svc:invoice-svc", label="Service", name="invoice-svc")],
        facts=[Fact(type="OWNS", src="per:kavya-rao", dst="svc:invoice-svc", evidence="x"),         # Person cannot OWN
               Fact(type="ON_CALL_FOR", src="per:ghost", dst="svc:invoice-svc", evidence="y")],     # unknown endpoint
    )
    report = ingest(TENANT, "data/raw/chat-invoice-oncall.md", extraction=bad)
    assert len(report["rejected"]) == 2 and not report["facts"]
    assert rows(graph, "MATCH (:Person {id: 'per:kavya-rao'})-[r:OWNS]->() RETURN count(r)") == [[0]]


# ---------------------------------------------------------------- other merge paths
def test_new_person_and_membership(graph):
    ex = Extraction(
        entities=[Entity(ref="Ishita Rao", label="Person", name="Ishita Rao", role="Backend Engineer"),
                  Entity(ref="team:search", label="Team", name="Search")],
        facts=[Fact(type="MEMBER_OF", src="Ishita Rao", dst="team:search", evidence="joins Team Search")],
    )
    report = ingest(TENANT, "data/raw/chat-new-hire.md", extraction=ex)
    assert report["entities"]["created"] == ["per:ishita-rao"]
    assert rows(graph, """MATCH (p:Person {id: 'per:ishita-rao'})-[r:MEMBER_OF]->(t:Team)
                          RETURN p.role, t.id, r.source_doc""") == [["Backend Engineer", "team:search", "doc:chat-new-hire"]]


def test_event_fact_and_evidence(graph):
    ex = Extraction(
        entities=[Entity(ref="per:vikram-shah", label="Person", name="Vikram Shah"),
                  Entity(ref="inc:0057", label="Incident", name="orders-api p99 latency spike")],
        facts=[Fact(type="RESOLVED", src="per:vikram-shah", dst="inc:0057", evidence="Vikram Shah resolved the incident")],
    )
    ingest(TENANT, "data/raw/pm-0057-orders-latency.md", extraction=ex)
    assert rows(graph, "MATCH (:Person {id: 'per:vikram-shah'})-[r:RESOLVED]->(:Incident {id: 'inc:0057'}) RETURN r.source_doc") == [["doc:pm-0057"]]
    assert rows(graph, "MATCH (:Document {id: 'doc:pm-0057'})-[:EVIDENCE_FOR]->(i) RETURN i.id") == [["inc:0057"]]


def test_new_decision_with_conventional_id(graph):
    ex = Extraction(
        entities=[Entity(ref="ADR-041", label="Decision", name="ADR-041: Cap search-api query timeouts at 800 ms",
                         summary="Slow queries exhausted search-api threads.", forbids=["change_timeout"]),
                  Entity(ref="per:dev-malhotra", label="Person", name="Dev Malhotra"),
                  Entity(ref="svc:search-api", label="Service", name="search-api")],
        facts=[Fact(type="MADE", src="per:dev-malhotra", dst="ADR-041", evidence="made by Dev Malhotra"),
               Fact(type="GOVERNS", src="ADR-041", dst="svc:search-api", evidence="search-api ... must time out")],
    )
    ingest(TENANT, "data/raw/adr-041-search-timeouts.md", extraction=ex)
    assert rows(graph, "MATCH (d:Decision {id: 'adr:041'})-[:GOVERNS]->(s) RETURN d.forbids, s.id") == [[["change_timeout"], "svc:search-api"]]


def test_state_change_without_replacement_closes_edge(graph):
    ex = Extraction(
        entities=[Entity(ref="per:farhan-qureshi", label="Person", name="Farhan Qureshi"),
                  Entity(ref="svc:billing-batch", label="Service", name="billing-batch")],
        facts=[Fact(type="ON_CALL_FOR", src="per:farhan-qureshi", dst="svc:billing-batch", ends=True, evidence="no longer on call")],
    )
    report = ingest(TENANT, "data/raw/live/chat-billing-move.md", extraction=ex)
    assert report["facts"][0]["action"] == "ended"
    assert run_tool(TENANT, "owner_of", {"service": "billing-batch"}).data["on_call"] == []


def test_ingest_tool_only_reads_data_raw(graph):
    with pytest.raises(ValueError):
        run_tool(TENANT, "ingest_document", {"path": ".env"})
    with pytest.raises(ValueError):
        run_tool(TENANT, "ingest_document", {"path": "data/raw/../../.env"})


def test_openai_compat_extraction_validates_and_retries():
    import anyio

    from backend.app.ingest.extract import _extract_openai_compat

    good = billing_move().model_dump_json()

    class Fake:
        def __init__(self):
            self.calls = []

        async def json(self, system, user):
            self.calls.append(user)
            return ('{"entities": [{"label": "Planet"}]}' if len(self.calls) == 1 else good), "groq:fake"

    fake = Fake()
    extraction, model = anyio.run(_extract_openai_compat, fake, read_document(BILLING_MOVE), "Team team:atlas Atlas")
    assert model == "groq:fake" and len(fake.calls) == 2 and "previous JSON was invalid" in fake.calls[1]
    assert {(f.type, f.src) for f in extraction.facts} == {("OWNS", "team:atlas"), ("ON_CALL_FOR", "per:farhan-qureshi")}


# ---------------------------------------------------------------- live model (optional)
@pytest.mark.skipif(not (os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")),
                    reason="no model key set")
def test_live_extraction_of_billing_move(graph, tmp_path, monkeypatch):
    from backend.app.ingest import extract as extract_module
    from backend.app.ingest.extract import extract

    monkeypatch.setattr(extract_module, "CACHE_DIR", tmp_path)  # never overwrite the committed demo cache

    extraction, origin = extract(read_document(BILLING_MOVE), graph, refresh=True)
    facts = {(f.type, f.src, f.dst) for f in extraction.facts}
    assert ("OWNS", "team:atlas", "svc:billing-batch") in facts
    assert origin != "cache"
