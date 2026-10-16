"""Agent loop: Claude chooses Triveni tools over MCP (Track 01).

The agent never imports the tools. It starts the MCP server for one tenant, lists the tools the
server offers, and every call goes through the MCP session. Each step is recorded (which tool,
with what input, the model's progress note on why, and the tool's provenance), which gives the
plan display and the evidence the final answer must cite.
"""
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[3]
BETAS = [
    "server-side-fallback-2026-07-01",  # fallbacks="default": re-run on a fallback model if a classifier declines
    "thinking-display-updates-2026-08-18",  # progress notes between tool calls -> the "why" of each step
]


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
    stop_reason: str = ""

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


def mcp_tools_for_claude(tools) -> list[dict]:
    """MCP tool listing -> Anthropic tool definitions (name, description, JSON schema), sorted for cache stability."""
    return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in sorted(tools, key=lambda t: t.name)]


def _progress_note(content) -> str:
    """Text the model wrote before its tool calls: progress-update thinking blocks, or plain text blocks."""
    notes = [getattr(b, "thinking", "") or "" for b in content if b.type == "thinking"]
    notes += [b.text for b in content if b.type == "text"]
    return " ".join(n.strip() for n in notes if n and n.strip())


async def run_agent(question: str, tenant: str, system: str, history: list | None = None,
                    client=None, max_turns: int = 10) -> AgentResult:
    client = client or anthropic.AsyncAnthropic()
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    messages = list(history or []) + [{"role": "user", "content": question}]
    result = AgentResult(question=question, tenant=tenant, answer="")

    async with stdio_client(server_params(tenant)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = mcp_tools_for_claude((await session.list_tools()).tools)

            for _ in range(max_turns):
                response = await client.beta.messages.create(
                    model=model, max_tokens=16000, betas=BETAS, fallbacks="default",
                    thinking={"type": "adaptive", "display": "updates"},
                    output_config={"effort": "medium"},  # multistep tool use: medium is the recommended start
                    system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                    tools=tools, messages=messages,
                )
                result.model, result.stop_reason = response.model, response.stop_reason
                if response.stop_reason == "refusal":
                    result.answer = "The request was declined by a safety classifier."
                    return result
                messages.append({"role": "assistant", "content": response.content})  # full content, thinking included
                calls = [b for b in response.content if b.type == "tool_use"]
                if not calls:
                    result.answer = "\n".join(b.text for b in response.content if b.type == "text").strip()
                    return result

                why = _progress_note(response.content)
                tool_results = []
                for call in calls:  # all results go back in one user message
                    t0 = time.perf_counter()
                    res = await session.call_tool(call.name, call.input)
                    ms = int((time.perf_counter() - t0) * 1000)
                    text = res.content[0].text if res.content else ""
                    sc = res.structured_content or {}
                    result.steps.append(Step(
                        tool=call.name, input=call.input, why=why, ok=not res.is_error,
                        explanation=sc.get("explanation", text if res.is_error else ""),
                        tracks=sc.get("tracks", []), sources=sc.get("sources", []), cypher=sc.get("cypher", ""),
                        params=sc.get("params", {}), paths=sc.get("paths", []), ms=ms))
                    tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": text,
                                         **({"is_error": True} if res.is_error else {})})
                messages.append({"role": "user", "content": tool_results})

    result.answer = result.answer or "Stopped: too many tool rounds without a final answer."
    return result


def print_result(r: AgentResult) -> None:
    print(f"\nQ ({r.tenant}): {r.question}\n")
    for i, s in enumerate(r.steps, 1):
        print(f"  {i}. [MCP] {s.tool}({json.dumps(s.input)})  {s.ms} ms  tracks {'/'.join(s.tracks)}")
        if s.why:
            print(f"     why: {s.why[:160]}")
        print(f"     -> {s.explanation[:200]}")
    print(f"\n{r.answer}\n\nsources: {', '.join(r.sources) or '-'}   tracks: {', '.join(r.tracks)}   model: {r.model}")
