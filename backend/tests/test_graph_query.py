"""graph_query: the model's own read-only Cypher, fenced in. Nothing it sends can write, invent schema, or run long."""
import pytest

from backend.app.graph.tenant import get_graph
from backend.app.tools import run_tool
from backend.app.tools.graph_query import UnsafeQuery, check

T = "test_acme"


def q(cypher, params=None):
    return run_tool(T, "graph_query", {"cypher": cypher, "purpose": "test", **({"params": params} if params else {})})


@pytest.mark.parametrize("cypher,reason", [
    ("MATCH (s:Service) SET s.x = 1 RETURN s", "SET"),
    ("MATCH (n) DETACH DELETE n", "DETACH"),
    ("CREATE (x:Service {id: 'svc:x'})", "must start with"),
    ("MERGE (x:Service {id: 'svc:x'}) RETURN x", "must start with"),
    ("MATCH (s) RETURN s; MATCH (n) DELETE n", "one statement"),
    ("CALL db.labels()", "must start with"),
    ("MATCH (s:Service) CALL algo.pageRank('Service', 'DEPENDS_ON') YIELD node RETURN node", "CALL"),
    ("MATCH (m:Microservice) RETURN m", "not in the schema: Microservice"),
    ("MATCH (p:Person)-[:MANAGES]->(t:Team) RETURN p", "not in the schema: MANAGES"),
])
def test_unsafe_or_invented_queries_are_refused(cypher, reason):
    with pytest.raises(UnsafeQuery) as e:
        check(cypher)
    assert reason in str(e.value)


def test_real_schema_passes_and_rows_are_capped():
    assert check("MATCH (p:Person)-[:AUTHORED]->(d:Deployment)<-[:CAUSED_BY]-(i:Incident) RETURN p.id").endswith("LIMIT 50")
    assert check("MATCH (d:Document) RETURN d.id LIMIT 1000").endswith("LIMIT 50")
    assert check("MATCH (s:Service) WHERE s.name = 'MERGE-api' RETURN s.id // CREATE (x)") == \
        "MATCH (s:Service) WHERE s.name = 'MERGE-api' RETURN s.id\nLIMIT 50"  # strings and comments are not clauses


def test_answers_what_no_fixed_tool_answers(loaded):
    r = q("MATCH (p:Person)-[:AUTHORED]->(d:Deployment)<-[:CAUSED_BY]-(i:Incident) "
          "WHERE p.id = $who RETURN p.id, d.id, i.id", {"who": "per:rohan-iyer"})
    assert r.outcome == "answered" and ["per:rohan-iyer", "dep:payments-api@2.12.0", "inc:0042"] in r.data["rows"]
    assert r.data["model_written"] is True and "inc:0042" in {n for p in r.paths for n in p["nodes"]}  # evidence


def test_paths_keep_their_edges(loaded):
    r = q("MATCH p=(a:Service {name: 'checkout-web'})-[:DEPENDS_ON*1..3]->(b:Service {name: 'payments-api'}) RETURN p LIMIT 1")
    path = r.paths[0]
    assert path["nodes"][0] == "svc:checkout-web" and path["nodes"][-1] == "svc:payments-api"
    assert path["edges"][0] == "DEPENDS_ON:svc:checkout-web->" + path["nodes"][1]


def test_database_errors_come_back_as_refused_and_nothing_is_written(loaded):
    r = q("MATCH (s:Service {tier: 1}) WHERE NOT EXISTS { MATCH (:Person)-[:ON_CALL_FOR]->(s) } RETURN s.id")
    assert r.outcome == "refused" and "FalkorDB rejected" in r.explanation  # the model can read why and fix it
    assert q("MATCH (s:Service) SET s.x = 1 RETURN s").outcome == "refused"
    assert get_graph(T).ro_query("MATCH (s:Service) WHERE s.x IS NOT NULL RETURN count(s)").result_set == [[0]]


def _scripted(responses):
    from types import SimpleNamespace as NS

    class Client:
        def __init__(self):
            self.requests, self.chat = [], NS(completions=NS(create=self._create))

        async def _create(self, **kw):
            self.requests.append(kw)
            return responses.pop(0)
    return Client()


def _oa(content="", calls=()):
    from types import SimpleNamespace as NS

    tcs = [NS(id=i, type="function", function=NS(name=n, arguments=a)) for i, n, a in calls] or None
    return NS(model="scripted", choices=[NS(message=NS(content=content, tool_calls=tcs))])


def test_graph_first_hands_the_model_the_graph_context(loaded):
    import anyio

    from backend.app.agents.loop import run_agent
    from backend.app.agents.triage import SYSTEM
    from backend.app.llm.providers import OpenAICompatProvider

    client = _scripted([_oa("Page Arjun Mehta (per:arjun-mehta).")])
    r = anyio.run(lambda: run_agent("payments-api is failing, who do I page?", T, SYSTEM, persist=False, graph_first=True,
                                    providers=[OpenAICompatProvider("groq", client=client, model="m")]))
    assert [s.tool for s in r.steps] == ["blast_radius", "similar_incidents", "recall"]  # run before the model
    assert all(s.why.startswith("graph-first") for s in r.steps) and len(client.requests) == 1  # one model round
    assert "[Graph context" in client.requests[0]["messages"][-1]["content"]
    assert r.verification["verdict"] == "verified" and not r.guard


def test_answers_from_a_model_written_query_carry_a_caveat(loaded):
    import json

    import anyio

    from backend.app.agents.loop import run_agent
    from backend.app.agents.triage import SYSTEM
    from backend.app.llm.providers import OpenAICompatProvider

    query = json.dumps({"cypher": "MATCH (p:Person {id: 'per:rohan-iyer'})-[:AUTHORED]->(d:Deployment) RETURN p.id, count(DISTINCT d)",
                        "purpose": "count deploys"})
    client = _scripted([_oa("", [("c1", "graph_query", query)]), _oa("per:rohan-iyer authored them.")])
    r = anyio.run(lambda: run_agent("how many deploys did Rohan Iyer author?", T, SYSTEM, persist=False,
                                    providers=[OpenAICompatProvider("groq", client=client, model="m")]))
    assert [s.tool for s in r.steps] == ["graph_query"] and "logic is not" in r.verification["caveat"]


def test_counting_rows_and_hidden_ties_are_rewritten(loaded):
    from backend.app.tools.graph_query import rewrite

    q, notes = rewrite("MATCH (p)-[:AUTHORED]->(d) RETURN p.name, count(d) AS n ORDER BY n DESC LIMIT 1")
    assert "count(DISTINCT d)" in q and q.endswith("LIMIT 5") and len(notes) == 2
    assert rewrite("MATCH (d) RETURN count(*), count(DISTINCT d)")[1] == []  # already right: untouched
    # the real mistake a model made: one deployment that caused two incidents was counted as two deployments
    r = q_ = run_tool(T, "graph_query", {"purpose": "t", "cypher":
        "MATCH (d:Deployment)<-[:AUTHORED]-(p:Person), (i:Incident)-[:CAUSED_BY]->(d) "
        "RETURN p.name AS engineer, count(d) AS n ORDER BY n DESC LIMIT 1"})
    assert all(row[1] == 1 for row in r.data["rows"]) and r.data["row_count"] == 5 and "Rewritten" in q_.explanation


@pytest.mark.parametrize("cypher,reason", [
    ("MATCH (d:Deployment)-[:CAUSED_BY]->(i:Incident) RETURN d.id", "CAUSED_BY goes (Incident)-[:CAUSED_BY]->(Deployment)"),
    ("MATCH (s:Service)-[:OWNS]->(t:Team) RETURN s.id", "OWNS goes (Team)-[:OWNS]->(Service)"),
    ("MATCH (p:Person)-[:OWNS]->(s:Service) RETURN p.id", "OWNS never connects Person and Service"),
])
def test_backwards_or_impossible_hops_are_refused(cypher, reason):
    """A backwards hop runs and returns nothing, which reads like absence; it is refused with the right direction."""
    with pytest.raises(UnsafeQuery) as e:
        check(cypher)
    assert reason in str(e.value)


def test_correct_directions_and_unions_pass():
    check("MATCH (d:Deployment)<-[:AUTHORED]-(p:Person), (i:Incident)-[:CAUSED_BY]->(d) RETURN p.id")
    check("MATCH (p:Person)-[r:OWNS|ON_CALL_FOR]->(s:Service) RETURN p.id")  # one valid type in a union is enough


def test_empty_model_query_is_not_proof_of_absence(loaded):
    r = q("MATCH (s:Service {name: 'no-such-service'}) RETURN s.id")
    assert r.outcome == "no_rows" and "not proof of absence" in r.explanation


def test_claiming_a_tool_that_did_not_run_is_unbacked(loaded):
    from backend.app.agents.verify import guard, verify

    g = get_graph(T)
    v = verify(g, "A `why_not` check found nothing.", set(), "q", "", tools_run={"graph_query"})
    assert v["unbacked"] == ["tool:why_not"] and v["verdict"] != "verified" and "why_not" in guard(v)
    assert verify(g, "A `why_not` check found nothing.", set(), "q", "", tools_run={"why_not"})["unbacked"] == []
