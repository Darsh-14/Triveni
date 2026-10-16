"""owner_of (Track 03) on the seeded test tenant."""
from backend.app.tools import REGISTRY, run_tool


def test_registry_has_owner_of():
    t = REGISTRY["owner_of"]
    assert t.read_only and t.tracks == ("03",)
    assert t.input_schema["required"] == ["service"]


def test_owner_and_oncall_with_sources(loaded, acme):
    gt = acme[1]["scenario1"]
    r = run_tool("test_acme", "owner_of", {"service": "payments-api"})
    assert [o["id"] for o in r.data["owners"]] == [gt["owner_team"]]
    assert [p["id"] for p in r.data["on_call"]] == [gt["on_call"]]
    assert r.sources == ["doc:oncall-schedule", "doc:service-catalog"]
    assert "OWNS:team:payments->svc:payments-api" in r.paths[0]["edges"]
    assert "MATCH" in r.cypher and r.params == {"service": "payments-api"} and r.tracks == ["03"]


def test_billing_batch_has_no_oncall(loaded):
    r = run_tool("test_acme", "owner_of", {"service": "billing-batch", "include_history": True})
    assert r.data["on_call"] == []
    assert [o["id"] for o in r.data["owners"]] == ["team:ledger"]
    assert [h["id"] for h in r.data["history"]] == ["team:ledger"]


def test_unknown_service(loaded):
    assert run_tool("test_acme", "owner_of", {"service": "no-such-svc"}).data == {"found": False, "service": "no-such-svc"}
