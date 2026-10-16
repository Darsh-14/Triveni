"""Track 03 read tools on the pristine seeded tenant (tenant_test_acme), checked against ground truth."""
from backend.app.tools import REGISTRY, run_tool
from backend.scripts import seed

T = "test_acme"


def test_every_tool_declares_schema_and_tracks():
    for name, t in REGISTRY.items():
        assert t.input_schema["type"] == "object" and t.input_schema["additionalProperties"] is False, name
        assert t.tracks and set(t.tracks) <= {"01", "02", "03"}, name
        assert "tenant" not in t.input_schema["properties"], name  # tenant comes from the request, never the model


def test_who_knows_matches_expertise_mirror(loaded, acme):
    expected = sorted(((p, w) for (p, s), w in seed.expertise_edges(acme[0]).items() if s == "svc:payments-api"),
                      key=lambda x: (-x[1], x[0]))[:5]
    r = run_tool(T, "who_knows", {"service": "payments-api"})
    assert [(p["id"], p["weight"]) for p in r.data["people"]] == expected
    for p in r.data["people"]:
        assert p["evidence"], p["id"]  # every ranked person has at least one evidence path
    assert all(len(path["nodes"]) in (2, 3) for path in r.paths) and "doc:pm-0042" in r.sources


def test_decision_trail_scenario2(loaded, acme):
    gt = acme[1]["scenario2"]
    r = run_tool(T, "decision_trail", {"service": "orders-api", "action": gt["action"]["kind"]})
    assert r.data["current"] == [gt["current_decision"]]
    assert r.data["chains"] == [gt["decision_trail"]]
    assert [s["document"] for s in r.data["stale_runbooks"]] == gt["stale_runbooks"]
    assert r.data["gate"] == {"action": "change_retry_policy", "allowed": False, "blocked_by": ["adr:019"]}
    assert set(gt["sources"]) <= set(r.sources)
    assert "SUPERSEDES:adr:019->adr:007" in {e for p in r.paths for e in p["edges"]}


def test_decision_trail_allows_unforbidden_action(loaded):
    r = run_tool(T, "decision_trail", {"service": "orders-api", "action": "create_ticket"})
    assert r.data["gate"]["allowed"] is True


def test_similar_incidents_scenario1(loaded, acme):
    gt = acme[1]["scenario1"]
    r = run_tool(T, "similar_incidents", {"service": "payments-api"})
    first = r.data["incidents"][0]
    assert first["id"] == gt["prior_incident"] and first["hops"] == 0
    assert first["resolved_by"] == ["per:priya-nair"]
    assert first["caused_by"] == [gt["prior_incident_cause"]] and first["postmortems"] == [gt["postmortem"]]
    neighbours = {d for r_, s, d, p in acme[0].edges if r_ == "DEPENDS_ON" and s == "svc:payments-api"} | \
                 {s for r_, s, d, p in acme[0].edges if r_ == "DEPENDS_ON" and d == "svc:payments-api"}
    assert all(i["via"] in neighbours for i in r.data["incidents"][1:])


def test_similar_incidents_from_incident_id(loaded):
    r = run_tool(T, "similar_incidents", {"incident": "inc:0057"})
    assert r.data["service"] == "svc:orders-api"
    assert "inc:0057" not in [i["id"] for i in r.data["incidents"]]


def test_why_not_scenario3(loaded, acme):
    gt = acme[1]["scenario3"]
    r = run_tool(T, "why_not", {"kind": "on_call", "service": "billing-batch"})
    assert r.data["exists"] is False and r.data["found"] == [] and r.data["history"] == []
    assert r.data["owner_team"] == gt["owner_team"]
    assert r.data["checked"].startswith("MATCH (p:Person)-[r:ON_CALL_FOR]->")
    ledger = {s for r_, s, d, p in acme[0].edges if r_ == "MEMBER_OF" and d == "team:ledger"}
    assert r.data["suggested_contacts"] and {c["id"] for c in r.data["suggested_contacts"]} <= ledger


def test_why_not_present_fact(loaded):
    r = run_tool(T, "why_not", {"kind": "on_call", "service": "payments-api"})
    assert r.data["exists"] is True and r.data["found"] == ["per:arjun-mehta"]


def test_why_not_orphan_has_no_owner(loaded):
    r = run_tool(T, "why_not", {"kind": "owner", "service": "legacy-fax-gateway"})
    assert r.data["exists"] is False and r.data["owner_team"] is None


def test_why_not_dependency_direction(loaded, acme):
    r = run_tool(T, "why_not", {"kind": "depends", "service": "payments-api", "other": "checkout-web"})
    assert r.data["exists"] is False
    assert r.data["reverse_path"] == acme[1]["eval"]["A2"]
    ok = run_tool(T, "why_not", {"kind": "depends", "service": "checkout-web", "other": "payments-api", "depth": 3})
    assert ok.data["exists"] is True and ok.data["path"][0] == "svc:checkout-web"
