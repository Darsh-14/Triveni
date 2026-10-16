"""Agent loop: a model chooses Triveni tools over MCP (Track 01).

The agent never imports the tools. It starts the MCP server for one tenant, lists the tools the
server offers, and every call goes through the MCP session. Each step is recorded (which tool,
with what input, the model's note on why, and the tool's provenance), which gives the plan
display and the evidence the final answer must cite.

Providers are tried in order (TRIVENI_LLM_PROVIDERS, default groq -> gemini -> anthropic -> rules).
If one is rate-limited or unreachable, the run restarts on the next and the switch is recorded.
"""
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.app.llm.providers import ProviderUnavailable, make, provider_order

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Step:
    tool: str
    input: dict
    why: str
    ok: bool
    explanation: str
    tracks: list[str]
    sources: list[str]
    cypher: str
    params: dict
    paths: list[dict]
    ms: int
    via: str = "mcp"


@dataclass
class AgentResult:
    question: str
    tenant: str
    answer: str
    steps: list[Step] = field(default_factory=list)
    model: str = ""
    fallbacks: list[str] = field(default_factory=list)  # providers that failed before this answer

    @property
    def tracks(self) -> list[str]:
        return sorted({t for s in self.steps for t in s.tracks})

    @property
    def sources(self) -> list[str]:
        return sorted({src for s in self.steps for src in s.sources})

    def to_dict(self) -> dict:
        return asdict(self) | {"tracks": self.tracks, "sources": self.sources}


def server_params(tenant: str) -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=["-m", "backend.app.mcp_server", "--tenant", tenant],
                                 cwd=str(REPO_ROOT), env=dict(os.environ))


def mcp_tools(tools) -> list[dict]:
    """MCP tool listing -> neutral tool definitions (name, description, JSON schema), sorted for stable prompts."""
    return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in sorted(tools, key=lambda t: t.name)]


async def _run_with(provider, session, tools, question, tenant, system, history, max_turns) -> AgentResult:
    result = AgentResult(question=question, tenant=tenant, answer="", model=provider.name)
    messages = list(history or []) + [provider.user(question)]
    for _ in range(max_turns):
        turn = await provider.turn(system, messages, tools)
        result.model = turn.model or result.model
        messages.append(turn.assistant_message or {"role": "assistant", "content": turn.text})
        if not turn.calls:
            result.answer = turn.text
            return result
        outputs = []
        for call in turn.calls:  # results of one turn go back together
            if call.args is None:
                text, is_error, sc, ms = f"Invalid JSON arguments: {call.raw_args[:200]}", True, {}, 0
            else:
                t0 = time.perf_counter()
                res = await session.call_tool(call.name, call.args)
                ms = int((time.perf_counter() - t0) * 1000)
                is_error, sc = bool(res.is_error), res.structured_content or {}
                text = res.content[0].text if res.content else ""
                if sc and not is_error:
                    # The model gets the answer and its sources; the UI keeps the full provenance (cypher,
                    # params, paths) from structured_content. Smaller prompts: faster, fewer rate limits.
                    text = json.dumps({k: sc.get(k) for k in ("explanation", "data", "sources")}, default=str)
            result.steps.append(Step(
                tool=call.name, input=call.args or {}, why=turn.text, ok=not is_error,
                explanation=sc.get("explanation", text if is_error else ""), tracks=sc.get("tracks", []),
                sources=sc.get("sources", []), cypher=sc.get("cypher", ""), params=sc.get("params", {}),
                paths=sc.get("paths", []), ms=ms))
            outputs.append((call, text, is_error))
        messages.extend(provider.tool_results(outputs))
    result.answer = "Stopped: too many tool rounds without a final answer."
    return result


async def run_agent(question: str, tenant: str, system: str, history: list | None = None,
                    providers: list | None = None, max_turns: int = 10) -> AgentResult:
    providers = providers if providers is not None else [make(n) for n in provider_order()]
    failed: list[str] = []
    async with stdio_client(server_params(tenant)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = mcp_tools((await session.list_tools()).tools)
            for provider in providers:
                try:
                    result = await _run_with(provider, session, tools, question, tenant, system, history, max_turns)
                except ProviderUnavailable as exc:
                    failed.append(str(exc)[:300])
                    continue
                result.fallbacks = failed
                return result
    return AgentResult(question=question, tenant=tenant, answer="No provider could answer.", fallbacks=failed)


def print_result(r: AgentResult) -> None:
    print(f"\nQ ({r.tenant}): {r.question}\n")
    for i, s in enumerate(r.steps, 1):
        print(f"  {i}. [MCP] {s.tool}({json.dumps(s.input)})  {s.ms} ms  tracks {'/'.join(s.tracks)}")
        if s.why:
            print(f"     why: {s.why[:160]}")
        print(f"     -> {s.explanation[:200]}")
    print(f"\n{r.answer}\n\nsources: {', '.join(r.sources) or '-'}   tracks: {', '.join(r.tracks)}   model: {r.model}")
    if r.fallbacks:
        print("fell back from: " + "; ".join(r.fallbacks))
