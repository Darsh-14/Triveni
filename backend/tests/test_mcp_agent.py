"""MCP server and agent loop (Track 01): tools are listed and called over MCP, never imported by the agent."""
import os
from types import SimpleNamespace as NS

import anyio
import pytest
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from backend.app.agents.loop import run_agent, server_params
from backend.app.llm.providers import (
    AnthropicProvider, OpenAICompatProvider, ProviderUnavailable, RulesProvider,
)
from backend.app.agents.triage import SYSTEM
from backend.app.tools import REGISTRY, run_tool

load_dotenv()


async def _with_session(tenant, fn):
    async with stdio_client(server_params(tenant)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def test_mcp_lists_registry_with_exact_schemas(loaded):
    async def go(s):
        return (await s.list_tools()).tools
    tools = anyio.run(_with_session, "test_acme", go)
    assert {t.name for t in tools} == set(REGISTRY) - {"claim_handoff", "complete_handoff"}  # code-only tools
    for t in tools:
        assert t.input_schema == REGISTRY[t.name].input_schema
        assert t.annotations.read_only_hint == REGISTRY[t.name].read_only


def test_mcp_call_returns_full_provenance(loaded):
    async def go(s):
        return await s.call_tool("blast_radius", {"service": "payments-api"})
    res = anyio.run(_with_session, "test_acme", go)
    direct = run_tool("test_acme", "blast_radius", {"service": "payments-api"}).to_dict()
    assert not res.is_error and res.structured_content == direct
    assert set(direct) >= {"data", "cypher", "params", "paths", "explanation", "tracks", "sources"}


def test_mcp_server_is_bound_to_its_tenant(loaded):
    async def go(s):
        return (await s.call_tool("owner_of", {"service": "payments-api"})).structured_content
    assert anyio.run(_with_session, "test_beta", go)["data"]["on_call"][0]["id"] == "per:lars-eriksen"
    assert anyio.run(_with_session, "test_acme", go)["data"]["on_call"][0]["id"] == "per:arjun-mehta"


def test_mcp_tool_error_is_returned_not_raised(loaded):
    async def go(s):
        return await s.call_tool("blast_radius", {"service": "payments-api", "depth": 9})
    res = anyio.run(_with_session, "test_acme", go)
    assert res.is_error and "depth" in res.content[0].text


# ---------------------------------------------------------------- agent loop with a scripted model
class ScriptedClaude:
    """Stands in for AsyncAnthropic: returns pre-written responses, records every request."""

    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.beta = NS(messages=NS(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot: the loop keeps appending
        return self.responses.pop(0)


def _tool_use(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


def test_agent_selects_tools_over_mcp_and_cites_them(loaded):
    claude = ScriptedClaude([
        NS(model="scripted", stop_reason="tool_use", content=[
            NS(type="thinking", thinking="Check what depends on payments-api and who is on call."),
            _tool_use("t1", "blast_radius", {"service": "payments-api"}),
            _tool_use("t2", "similar_incidents", {"service": "payments-api"}),
        ]),
        NS(model="scripted", stop_reason="end_turn", content=[
            NS(type="text", text="Page per:arjun-mehta. Affected: svc:orders-api ... [doc:pm-0042]"),
        ]),
    ])
    r = anyio.run(lambda: run_agent("payments-api is failing", "test_acme", SYSTEM, persist=False, providers=[AnthropicProvider(client=claude)]))

    assert [s.tool for s in r.steps] == ["blast_radius", "similar_incidents"] and all(s.via == "mcp" for s in r.steps)
    assert r.steps[0].why.startswith("Check what depends")
    assert "5 service(s) depend on payments-api" in r.steps[0].explanation  # real graph result, via MCP
    assert "doc:pm-0042" in r.sources and set(r.tracks) >= {"01", "03"}
    assert r.answer.startswith("Page per:arjun-mehta")

    first, second = claude.requests
    assert {t["name"] for t in first["tools"]} == set(REGISTRY) - {"claim_handoff", "complete_handoff"}  # the MCP list
    results = second["messages"][-1]["content"]
    assert [x["tool_use_id"] for x in results] == ["t1", "t2"]  # both results in ONE user message
    assert first["fallbacks"] == "default" and first["output_config"] == {"effort": "medium"}


def test_agent_passes_tool_errors_back_to_model(loaded):
    claude = ScriptedClaude([
        NS(model="scripted", stop_reason="tool_use", content=[_tool_use("t1", "blast_radius", {"service": "payments-api", "depth": 9})]),
        NS(model="scripted", stop_reason="end_turn", content=[NS(type="text", text="Retried with valid depth.")]),
    ])
    r = anyio.run(lambda: run_agent("x", "test_acme", SYSTEM, persist=False, providers=[AnthropicProvider(client=claude)]))
    assert r.steps[0].ok is False
    assert claude.requests[1]["messages"][-1]["content"][0]["is_error"] is True


# ---------------------------------------------------------------- OpenAI-compatible providers (Groq, Gemini)
class ScriptedOpenAI:
    """Stands in for AsyncOpenAI pointed at Groq/Gemini."""

    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.chat = NS(completions=NS(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _oa(content="", calls=(), model="scripted-oa"):
    tcs = [NS(id=i, type="function", function=NS(name=n, arguments=a),
              extra_content={"google": {"thought_signature": f"sig-{i}"}}) for i, n, a in calls] or None
    return NS(model=model, choices=[NS(message=NS(content=content, tool_calls=tcs))])


def test_openai_compat_provider_over_mcp(loaded):
    oa = ScriptedOpenAI([
        _oa("Checking dependents first.", [("c1", "blast_radius", '{"service": "payments-api"}'),
                                           ("c2", "owner_of", '{"service": "payments-api"}')]),
        _oa("Page per:arjun-mehta [doc:oncall-schedule]."),
    ])
    r = anyio.run(lambda: run_agent("payments-api is failing", "test_acme", SYSTEM, persist=False,
                                    providers=[OpenAICompatProvider("groq", client=oa, model="test-model")]))
    assert [s.tool for s in r.steps] == ["blast_radius", "owner_of"] and r.steps[0].why == "Checking dependents first."
    assert r.model == "groq:scripted-oa" and r.answer.startswith("Page per:arjun-mehta")
    first, second = oa.requests
    assert first["messages"][0]["role"] == "system" and first["tool_choice"] == "auto"
    assert {t["function"]["name"] for t in first["tools"]} == set(REGISTRY) - {"claim_handoff", "complete_handoff"}
    tool_msgs = [m for m in second["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"]
    assert all("name" not in m for m in tool_msgs)  # Groq rejects messages[].name
    echoed = second["messages"][-3]["tool_calls"][0]
    assert echoed["function"].name == "blast_radius"
    assert echoed["extra_content"] == {"google": {"thought_signature": "sig-c1"}}  # Gemini needs it back unchanged


def test_invalid_tool_arguments_are_not_sent_to_mcp(loaded):
    oa = ScriptedOpenAI([_oa("", [("c1", "blast_radius", '{"service": ')]), _oa("Sorry, retrying.")])
    r = anyio.run(lambda: run_agent("x", "test_acme", SYSTEM, persist=False,
                                    providers=[OpenAICompatProvider("gemini", client=oa, model="m")]))
    assert r.steps[0].ok is False and "Invalid JSON" in r.steps[0].explanation


def test_falls_back_to_next_provider(loaded):
    import httpx
    import openai

    limited = openai.RateLimitError("rate limited", body=None,
                                    response=httpx.Response(429, request=httpx.Request("POST", "http://x")))
    groq = OpenAICompatProvider("groq", client=ScriptedOpenAI([limited]), model="m")
    gemini = OpenAICompatProvider("gemini", client=ScriptedOpenAI([_oa("Done via gemini.", model="g")]), model="m")
    r = anyio.run(lambda: run_agent("hello", "test_acme", SYSTEM, persist=False, providers=[groq, gemini]))
    assert r.model == "gemini:g" and r.answer == "Done via gemini."
    assert len(r.fallbacks) == 1 and r.fallbacks[0].startswith("groq: RateLimitError")


class _Down:
    name, model = "groq", "m"

    def user(self, text):
        return {"role": "user", "content": text}

    async def turn(self, *args):
        raise ProviderUnavailable("groq: down")


def test_all_models_down_uses_rules(loaded):
    r = anyio.run(lambda: run_agent("payments-api is failing, who do I page?", "test_acme", SYSTEM, persist=False,
                                    providers=[_Down(), RulesProvider()]))
    assert r.model == "rules" and r.fallbacks == ["groq: down"]
    assert [s.tool for s in r.steps] == ["blast_radius", "similar_incidents", "recall"] and all(s.via == "mcp" for s in r.steps)
    assert r.answer.startswith("Rules mode") and "Page Arjun Mehta" in r.answer


@pytest.mark.parametrize("question,plan", [
    ("payments-api is failing, what's affected?", ["blast_radius", "similar_incidents", "recall"]),
    ("Can we change the retry policy on orders-api?", ["decision_trail"]),
    ("Who is on call for billing-batch?", ["why_not"]),
    ("Who knows payments-api best?", ["who_knows"]),
    ("Who owns billing-batch now?", ["owner_of"]),
    ("How is per:priya-nair connected to svc:billing-batch?", ["shortest_path"]),
    ("Which engineers are single points of knowledge?", ["key_people"]),
    ("Which services are orphaned?", ["find_orphans"]),
    ("What are our most critical services?", ["critical_services"]),
    ("hello", []),
])
def test_rules_planner(question, plan):
    assert [n for n, _ in RulesProvider.plan(question)] == plan


def test_rules_retry_question_checks_the_action():
    assert RulesProvider.plan("Can we change the retry policy on orders-api?")[0][1] == {
        "service": "orders-api", "action": "change_retry_policy"}


@pytest.mark.skipif(not (os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY")), reason="no GROQ/GEMINI key")
def test_live_model_agent_scenario1(loaded):
    r = anyio.run(lambda: run_agent("payments-api is failing, what's affected and who do I page?", "test_acme", SYSTEM, persist=False))
    assert r.model != "rules", r.fallbacks
    assert "blast_radius" in [s.tool for s in r.steps]
    assert "arjun" in r.answer.lower()


@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
def test_live_anthropic_agent_scenario1(loaded, acme):
    r = anyio.run(lambda: run_agent("payments-api is failing, what's affected and who do I page?", "test_acme", SYSTEM, persist=False,
                                    providers=[AnthropicProvider()]))
    assert "blast_radius" in [s.tool for s in r.steps]
    assert "arjun" in r.answer.lower()
