"""HTTP API: the UI's only entry point. Uses the seeded test tenants."""
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture(scope="module")
def client(loaded):
    return TestClient(app)


def test_health_and_tools(client):
    assert client.get("/api/health").json()["falkordb"] is True
    names = {t["name"] for t in client.get("/api/tools").json()}
    assert {"blast_radius", "owner_of", "decision_trail", "why_not"} <= names


def test_tool_endpoint_returns_provenance(client, acme):
    r = client.post("/api/tools/blast_radius", json={"tenant": "test_acme", "args": {"service": "payments-api"}})
    assert r.status_code == 200
    body = r.json()
    assert sorted(a["id"] for a in body["data"]["affected"]) == acme[1]["scenario1"]["blast_radius_3"]
    assert body["cypher"] and body["paths"] and body["tracks"] == ["01"]


def test_bad_requests(client):
    assert client.post("/api/tools/blast_radius", json={"tenant": "Bad!", "args": {}}).status_code == 400
    assert client.post("/api/tools/blast_radius", json={"tenant": "nobody", "args": {}}).status_code == 404
    assert client.post("/api/tools/nope", json={"tenant": "test_acme", "args": {}}).status_code == 404
    bad = client.post("/api/tools/blast_radius", json={"tenant": "test_acme", "args": {"service": "payments-api", "depth": 9}})
    assert bad.status_code == 400


def test_graph_endpoints(client, acme):
    ov = client.get("/api/graph/overview", params={"tenant": "test_acme"}).json()
    assert len([n for n in ov["nodes"] if n["label"] == "Service"]) == 40
    assert {"type": "DEPENDS_ON", "source": "svc:orders-api", "target": "svc:payments-api"} in ov["edges"]
    nodes = client.post("/api/graph/nodes", json={"tenant": "test_acme", "ids": ["svc:payments-api", "per:arjun-mehta"]}).json()
    assert {(n["id"], n["label"]) for n in nodes} == {("svc:payments-api", "Service"), ("per:arjun-mehta", "Person")}


def test_document_endpoint(client):
    d = client.get("/api/documents/doc:pm-0042", params={"tenant": "test_acme"}).json()
    assert d["kind"] == "postmortem" and "svc:payments-api" in d["mentions"] and d["author"] == "Priya Nair"
    assert client.get("/api/documents/doc:none", params={"tenant": "test_acme"}).status_code == 404


def test_tenant_isolation_over_http(client):
    q = {"args": {"service": "payments-api"}}
    acme = client.post("/api/tools/owner_of", json={"tenant": "test_acme", **q}).json()
    beta = client.post("/api/tools/owner_of", json={"tenant": "test_beta", **q}).json()
    assert acme["data"]["on_call"][0]["id"] == "per:arjun-mehta" and beta["data"]["on_call"][0]["id"] == "per:lars-eriksen"
