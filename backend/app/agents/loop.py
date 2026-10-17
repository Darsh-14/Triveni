"""Agent loop: a model chooses Triveni tools over MCP (Track 01).

The agent never imports the tools. It starts the MCP server for one tenant, lists the tools the
server offers, and every call goes through the MCP session. Each step is recorded (which tool,
with what input, the model's note on why, and the tool's provenance), which gives the plan
display and the evidence the final answer must cite.

Providers are tried in order (TRIVENI_LLM_PROVIDERS, default groq -> gemini -> anthropic -> rules).
If one is rate-limited or unreachable, the run restarts on the next and the switch is recorded.
"""
import inspect
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.app.graph.tenant import get_graph
from backend.app.llm.providers import ProviderUnavailable, make, provider_order
from backend.app.memory.conversation import append_message, load_history, start_conversation
from backend.app.memory.remember import remember
from backend.app.agents.verify import evidence_ids, verify

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
    data: dict = field(default_factory=dict)  # the tool's result data, so the UI can render it (owner, recall, changes)


@dataclass
class AgentResult:
    question: str
    tenant: str
    answer: str
    steps: list[Step] = field(default_factory=list)
    model: str = ""
    fallbacks: list[str] = field(default_factory=list)  # providers that failed before this answer
    conversation_id: str = ""
    episode: str = ""  # memory written for this answer (by the model via `remember`, or automatically)
    tokens: int = 0   # model tokens used for this answer
    verification: dict = field(default_factory=dict)  # deterministic proof check of the answer (verify.py)

    @property
    def tracks(self) -> list[str]:
        return sorted({t for s in self.steps for t in s.tracks})

    @property
    def sources(self) -> list[str]:
        return sorted({src for s in self.steps for src in s.sources})

    def to_dict(self) -> dict:
        return asdict(self) | {"tracks": self.tracks, "sources": self.sources}  # _evidence is not a field: not exported


def server_params(tenant: str, agent: str = "agent:triage") -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable,
                                 args=["-m", "backend.app.mcp_server", "--tenant", tenant, "--agent", agent],
                                 cwd=str(REPO_ROOT), env=dict(os.environ))


def mcp_tools(tools) -> list[dict]:
    """MCP tool listing -> neutral tool definitions (name, description, JSON schema), sorted for stable prompts."""
    return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in sorted(tools, key=lambda t: t.name)]


async def _run_with(provider, session, tools, question, tenant, system, history, max_turns, progress) -> AgentResult:
    result = AgentResult(question=question, tenant=tenant, answer="", model=provider.name)
    messages = list(history or []) + [provider.user(question)]
    # what the answer may cite: ids the user gave (question + earlier turns) and ids any tool returned this run
    result._evidence = evidence_ids(question + " " + " ".join(str(m.get("content", "")) for m in history or []))
    for n in range(max_turns):
        progress(f"{provider.name}: thinking" + (f" (round {n + 1})" if n else ""))
        turn = await provider.turn(system, messages, tools)
        result.model = turn.model or result.model
        result.tokens += getattr(turn, "tokens", 0) or 0
        messages.append(turn.assistant_message or {"role": "assistant", "content": turn.text})
        if not turn.calls:
            result.answer = turn.text
            return result
        outputs = []
        for call in turn.calls:  # results of one turn go back together
            if call.args is None:
                text, is_error, sc, ms = f"Invalid JSON arguments: {call.raw_args[:200]}", True, {}, 0
            else:
                progress(f"{provider.name}: calling {call.name} over MCP")
                t0 = time.perf_counter()
                res = await session.call_tool(call.name, call.args)
                ms = int((time.perf_counter() - t0) * 1000)
                is_error, sc = bool(res.is_error), res.structured_content or {}
                if sc and not is_error:
                    result._evidence |= evidence_ids(json.dumps(sc, default=str))
                text = res.content[0].text if res.content else ""
                if sc and not is_error:
                    text = for_model(sc)
            result.steps.append(Step(
                tool=call.name, input=call.args or {}, why=turn.text, ok=not is_error,
                explanation=sc.get("explanation", text if is_error else ""), tracks=sc.get("tracks", []),
                sources=sc.get("sources", []), cypher=sc.get("cypher", ""), params=sc.get("params", {}),
                paths=sc.get("paths", []), ms=ms, data=sc.get("data", {}) if not is_error else {}))
            outputs.append((call, text, is_error))
        messages.extend(provider.tool_results(outputs))
    result.answer = "Stopped: too many tool rounds without a final answer."
    return result


MEMORY_PREFIXES = ("svc:", "inc:", "per:")
MAX_RESULT_CHARS = 2500  # per tool result sent to the model (~600 tokens); free tiers cap input tokens per minute
MAX_HISTORY = 8          # earlier messages of the conversation sent to the model


def for_model(sc: dict) -> str:
    """What the model sees of a tool result: explanation, data, sources. The UI keeps the full provenance
    (cypher, params, paths) from structured_content. Large data is cut, and the cut is marked."""
    text = json.dumps({k: sc.get(k) for k in ("explanation", "data", "sources")}, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    data = json.dumps(sc.get("data"), default=str)[: MAX_RESULT_CHARS - 600]
    return json.dumps({"explanation": sc.get("explanation"), "sources": sc.get("sources"),
                       "data_truncated": data + " ...(truncated; ask a narrower question for more)"})


def _involved(result: AgentResult) -> list[str]:
    """Entities an answer touched (from its evidence paths), for the automatic episode."""
    seen = []
    for step in result.steps:
        for path in step.paths:
            for node in path["nodes"]:
                if node.startswith(MEMORY_PREFIXES) and node not in seen:
                    seen.append(node)
    return seen[:10]


def _persist(tenant: str, agent: str, user_id: str, conversation_id: str | None, result: AgentResult) -> None:
    """Conversation + episodic memory, written after the answer. All state lives in the tenant graph."""
    graph = get_graph(tenant)
    cid = start_conversation(graph, user_id, agent=agent, conversation_id=conversation_id)
    append_message(graph, cid, "user", result.question)
    append_message(graph, cid, "assistant", result.answer)
    result.conversation_id = cid
    stored = [s for s in result.steps if s.tool == "remember" and s.ok]
    if stored:
        result.episode = stored[-1].explanation.split(" ")[1]  # "Stored ep:... by ..."
    elif result.steps:
        result.episode = remember(graph, agent, result.question, "answered", _involved(result))["episode"]


def history_messages(tenant: str, conversation_id: str | None) -> list[dict]:
    """Rebuild the model's context from the graph (text turns only; tool traces are in the episodes)."""
    if not conversation_id:
        return []
    messages = [{"role": m["role"], "content": m["text"]} for m in load_history(get_graph(tenant), conversation_id)
                if m["role"] in ("user", "assistant") and m["text"]]
    return messages[-MAX_HISTORY:]


async def run_agent(question: str, tenant: str, system: str, history: list | None = None,
                    providers: list | None = None, max_turns: int = 10, conversation_id: str | None = None,
                    user_id: str = "user:demo", agent: str = "agent:triage", persist: bool = True,
                    max_wait: float = 30.0, progress: Callable[[str], None] | None = None) -> AgentResult:
    """max_wait: longest rate-limit wait per model call before falling back (the UI uses 0).
    progress: called with short status lines (provider tried, tool called, fallbacks) for a live status display."""
    progress = progress or (lambda _msg: None)
    providers = providers if providers is not None else [make(n, max_wait=max_wait) for n in provider_order()]
    if history is None:
        history = history_messages(tenant, conversation_id)
    failed: list[str] = []
    result = None
    async with stdio_client(server_params(tenant, agent)) as (read, write):
        async with ClientSession(read, write) as session:
            progress("starting the MCP server and listing tools")
            await session.initialize()
            tools = mcp_tools((await session.list_tools()).tools)
            for provider in providers:
                try:
                    result = await _run_with(provider, session, tools, question, tenant, system, history, max_turns, progress)
                except ProviderUnavailable as exc:
                    failed.append(str(exc)[:300])
                    progress(f"{provider.name} unavailable ({_reason(exc)}), falling back")
                    continue
                break
    for provider in providers:  # release HTTP clients while the event loop is still running
        close = getattr(getattr(provider, "client", None), "close", None)
        if close is not None and inspect.iscoroutinefunction(close):
            await close()
    result = result or AgentResult(question=question, tenant=tenant, answer="No provider could answer.")
    result.fallbacks = failed
    progress("checking every cited id against the graph")
    result.verification = verify(get_graph(tenant), result.answer, getattr(result, "_evidence", set()))
    if persist:
        _persist(tenant, agent, user_id, conversation_id, result)
    return result


def _reason(exc: Exception) -> str:
    """Short human reason for a provider failure: 'rate limited', 'quota exhausted', 'timeout', ..."""
    text = str(exc).lower()
    for needle, reason in (("quota", "quota exhausted"), ("429", "rate limited"), ("rate", "rate limited"),
                           ("413", "request too large"), ("timeout", "timed out"), ("timed out", "timed out"),
                           ("connection", "unreachable"), ("401", "bad key"), ("403", "forbidden")):
        if needle in text:
            return reason
    return "error"


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
    v = r.verification
    if v:
        print(f"proof check: {v['verdict']} ({len(v['grounded'])}/{v['cited']} cited ids grounded"
              + (f"; unbacked {', '.join(v['unbacked'])}" if v["unbacked"] else "")
              + (f"; UNKNOWN {', '.join(v['unknown'])}" if v["unknown"] else "") + ")")
