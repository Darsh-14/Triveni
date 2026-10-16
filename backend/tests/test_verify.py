"""Deterministic proof check: cited ids must exist in the graph and come from this run's tool results."""
from types import SimpleNamespace as NS

import anyio

from backend.app.agents.loop import run_agent
from backend.app.agents.triage import SYSTEM
from backend.app.agents.verify import cited_ids, verify
from backend.app.graph.tenant import get_graph
from backend.app.llm.providers import OpenAICompatProvider


def test_cited_ids_are_extracted():
    assert cited_ids("Page per:arjun-mehta. See [doc:pm-0042], dep:payments-api@2.12.0.") == [
        "per:arjun-mehta", "doc:pm-0042", "dep:payments-api@2.12.0"]


def test_verdicts(loaded):
    g = get_graph("test_acme")
    assert verify(g, "Page per:arjun-mehta [doc:pm-0042]", {"per:arjun-mehta", "doc:pm-0042"})["verdict"] == "verified"
    v = verify(g, "Page per:arjun-mehta and per:kavya-rao", {"per:arjun-mehta"})
    assert v["verdict"] == "partially_verified" and v["unbacked"] == ["per:kavya-rao"]
    v = verify(g, "Page per:imaginary-person", set())
    assert v["verdict"] == "unverified" and v["unknown"] == ["per:imaginary-person"]
    assert verify(g, "No ids here.", set())["verdict"] == "no_citations"


class Scripted:
    def __init__(self, responses):
        self.responses = list(responses)
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, **kw):
        return self.responses.pop(0)


def _oa(content="", calls=()):
    tcs = [NS(id=i, type="function", function=NS(name=n, arguments=a)) for i, n, a in calls] or None
    return NS(model="scripted", choices=[NS(message=NS(content=content, tool_calls=tcs))])


def test_agent_answer_is_checked_against_its_own_tool_results(loaded):
    model = Scripted([_oa("", [("c1", "owner_of", '{"service": "payments-api"}')]),
                      _oa("Page per:arjun-mehta (team:payments) [doc:oncall-schedule]. Also per:ghost-engineer.")])
    r = anyio.run(lambda: run_agent("who do I page for payments-api?", "test_acme", SYSTEM, persist=False,
                                    providers=[OpenAICompatProvider("groq", client=model, model="m")]))
    v = r.verification
    assert set(v["grounded"]) == {"per:arjun-mehta", "team:payments", "doc:oncall-schedule"}
    assert v["unknown"] == ["per:ghost-engineer"] and v["verdict"] == "unverified"
    assert "_evidence" not in r.to_dict()
