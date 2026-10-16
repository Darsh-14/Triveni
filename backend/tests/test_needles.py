"""Each planted demo needle (MVP.md Section 5) is in the loaded graph, checked with Cypher."""
from backend.scripts import seed


def rows(graph, query, **params):
    return graph.ro_query(query, params).result_set


def test_scenario1_payments(loaded, acme):
    g, gt = loaded["acme"], acme[1]["scenario1"]
    svc = gt["service"]
    blast = rows(g, "MATCH (d:Service)-[:DEPENDS_ON*1..3]->(s:Service {id: $svc}) RETURN DISTINCT d.id", svc=svc)
    assert sorted(r[0] for r in blast) == gt["blast_radius_3"]
    assert rows(g, "MATCH (p:Person)-[r:ON_CALL_FOR]->(:Service {id: $svc}) WHERE r.valid_to IS NULL RETURN p.id",
                svc=svc) == [[gt["on_call"]]]
    assert rows(g, "MATCH (t:Team)-[r:OWNS]->(:Service {id: $svc}) WHERE r.valid_to IS NULL RETURN t.id",
                svc=svc) == [[gt["owner_team"]]]
    assert rows(g, """MATCH (p:Person)-[:AUTHORED]->(d:Deployment)-[:DEPLOYED_TO]->(:Service {id: $svc})
                      RETURN d.id, p.id ORDER BY d.ts DESC LIMIT 1""", svc=svc) == [[gt["last_deploy"], gt["last_deploy_author"]]]
    assert rows(g, """MATCH (doc:Document {kind: 'postmortem'})-[:EVIDENCE_FOR]->(i:Incident)-[:CAUSED_BY]->(d:Deployment)
                      -[:DEPLOYED_TO]->(:Service {id: $svc}) RETURN i.id, d.id, doc.id""",
                svc=svc) == [[gt["prior_incident"], gt["prior_incident_cause"], gt["postmortem"]]]


def test_scenario2_decision_trail_and_stale_runbook(loaded, acme):
    g, gt = loaded["acme"], acme[1]["scenario2"]
    trail = rows(g, """MATCH (new:Decision)-[:SUPERSEDES]->(old:Decision)-[:GOVERNS]->(s:Service {id: $svc})
                       MATCH (new)-[:GOVERNS]->(s)
                       MATCH (src_new:Document)-[:EVIDENCE_FOR]->(new)
                       MATCH (src_old:Document)-[:EVIDENCE_FOR]->(old)
                       RETURN new.id, old.id, new.forbids, src_new.id, src_old.id""", svc=gt["service"])
    assert trail == [["adr:019", "adr:007", ["change_retry_policy"], "doc:adr-019", "doc:adr-007"]]
    stale = rows(g, """MATCH (d:Document {kind: 'runbook'})-[:MENTIONS]->(old:Decision)<-[:SUPERSEDES]-(:Decision)
                       MATCH (old)-[:GOVERNS]->(:Service {id: $svc}) RETURN d.id""", svc=gt["service"])
    assert [r[0] for r in stale] == gt["stale_runbooks"]


def test_scenario3_no_oncall_and_orphans(loaded, acme):
    g, gt = loaded["acme"], acme[1]["scenario3"]
    assert rows(g, """MATCH (s:Service {id: $svc}) OPTIONAL MATCH (p:Person)-[r:ON_CALL_FOR]->(s)
                      RETURN count(p)""", svc=gt["service"]) == [[0]]
    orphans = rows(g, """MATCH (s:Service) OPTIONAL MATCH (s)<-[r:RESPONSIBLE_FOR]-()
                         WITH s, count(r) AS c WHERE c = 0 RETURN s.id ORDER BY s.id""")
    assert [r[0] for r in orphans] == gt["orphans"]


def test_scenario4_knows_projection_matches_mirror(loaded, acme):
    got = {(p, s): w for p, s, w in rows(loaded["acme"], "MATCH (p:Person)-[k:KNOWS]->(s:Service) RETURN p.id, s.id, k.weight")}
    assert got == seed.expertise_edges(acme[0])
    back = rows(loaded["acme"], "MATCH (:Service)-[k:KNOWN_BY]->(:Person) RETURN count(k)")[0][0]
    assert back == len(got)


def test_scenario5_memory(loaded, acme):
    g, gt = loaded["acme"], acme[1]["scenario5"]
    assert rows(g, """MATCH (:Agent {id: 'agent:triage'})-[:RAN]->(e:Episode)-[:INVOLVED]->(:Service {id: 'svc:payments-api'})
                      MATCH (e)-[:LEARNED]->(l:Lesson)
                      MATCH (e)-[:USED]->(pr:Procedure)-[:FOR]->(:Service {id: 'svc:payments-api'})
                      RETURN e.id, l.id, pr.id, pr.success_count""") == [[gt["episode"], gt["lesson"], gt["procedure"], 2]]
    msgs = rows(g, "MATCH (:Conversation {id: $c})-[:HAS_MESSAGE]->(m:Message) RETURN m.seq ORDER BY m.seq", c=gt["conversation"])
    assert [r[0] for r in msgs] == list(range(gt["messages"]))
    chain = rows(g, "MATCH p=(:Message {seq: 0})-[:NEXT*]->(last:Message) RETURN max(length(p))")
    assert chain == [[gt["messages"] - 1]]


def test_scenario6_agents_no_handoffs(loaded, acme):
    g, gt = loaded["acme"], acme[1]["scenario6"]
    assert sorted(r[0] for r in rows(g, "MATCH (a:Agent) RETURN a.id")) == gt["agents"]
    assert rows(g, "MATCH (h:Handoff) RETURN count(h)") == [[0]]


def test_scenario7_current_owner_with_source(loaded, acme):
    g, gt = loaded["acme"], acme[1]["scenario7"]
    assert rows(g, """MATCH (t:Team)-[r:OWNS]->(:Service {id: $svc}) WHERE r.valid_to IS NULL
                      RETURN t.id, r.source_doc, r.valid_from""", svc=gt["service"]) == [
        [gt["owner_before"], gt["source_before"], "2026-03-01T00:00:00Z"]]
    assert rows(g, "MATCH (p:Person)-[:MEMBER_OF]->(:Team {id: $t}) RETURN count(p)", t=gt["owner_after"])[0][0] > 0


def test_scenario7b_billing_decision_chain(loaded, acme):
    g = loaded["acme"]
    assert rows(g, """MATCH (new:Decision)-[:SUPERSEDES]->(old:Decision)-[:GOVERNS]->(:Service {id: 'svc:billing-batch'})
                      MATCH (d:Document {kind: 'runbook'})-[:MENTIONS]->(old) RETURN new.id, old.id, d.id""") == [
        ["adr:023", "adr:011", "doc:rb-billing-rerun"]]


def test_scenario8_beta_answers_differently(loaded, beta):
    gt = beta[1]["scenario8"]
    q = "MATCH (p:Person)-[r:ON_CALL_FOR]->(:Service {id: $svc}) WHERE r.valid_to IS NULL RETURN p.id"
    assert rows(loaded["beta"], q, svc=gt["service"]) == [[gt["on_call"]]]
    assert rows(loaded["acme"], q, svc=gt["service"]) == [["per:arjun-mehta"]]
