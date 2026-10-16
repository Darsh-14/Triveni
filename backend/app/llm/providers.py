"""Model providers behind one small interface, so the agent and ingestion don't care which model runs.

  groq, gemini   OpenAI-compatible chat completions (free tiers; `openai` SDK with a base_url)
  anthropic      Claude via the anthropic SDK (optional, if a key is ever available)
  rules          no model at all: a deterministic planner (agent only), always available as the last resort

Order and models come from env (see .env.example). A provider is "available" when its key is set.
"""
import json
import os
import re
from dataclasses import dataclass, field

OPENAI_COMPAT = {
    # name: (base_url, key env var, model env var, default model)
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "TRIVENI_GROQ_MODEL", "qwen/qwen3.8-27b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "TRIVENI_GEMINI_MODEL", "gemini-3.8-flash"),
}
DEFAULT_ORDER = "groq,gemini,anthropic,rules"


@dataclass
class Call:
    id: str
    name: str
    args: dict | None  # None when the model sent arguments that are not valid JSON
    raw_args: str = ""


@dataclass
class Turn:
    text: str  # final answer, or progress note when there are calls
    calls: list[Call] = field(default_factory=list)
    assistant_message: object = None  # provider-native message to append to the history
    model: str = ""
    tokens: int = 0  # prompt + completion tokens reported by the provider


class ProviderUnavailable(RuntimeError):
    """Raised for errors worth falling back on (rate limit, auth, network, server)."""


def _dump(obj) -> dict:
    """SDK object -> plain dict, keeping provider extras (e.g. extra_content) that the SDK passes through."""
    return obj.model_dump(exclude_none=True) if hasattr(obj, "model_dump") else dict(vars(obj))


def _wait_seconds(exc) -> float | None:
    """How long the provider asks us to wait (retry-after / x-ratelimit-reset-*), capped at 30 s; None if not a limit."""
    response = getattr(exc, "response", None)
    if response is None or response.status_code not in (413, 429):
        return None
    headers = response.headers
    for key in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        value = headers.get(key)
        if not value:
            continue
        total, matched = 0.0, False
        for amount, unit in re.findall(r"([0-9.]+)(ms|s|m|h)?", value):
            matched = True
            total += float(amount) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "": 1}[unit]
        if matched:
            return min(total + 0.5, 30.0) if total <= 30 else None  # a long wait means try the next provider
    return 10.0


async def _with_limit_retry(call, max_wait: float = 30.0):
    """Call once; if the provider says "rate limited, retry in N s" with N <= max_wait, wait and retry once.
    max_wait=0 never waits: the caller moves on to the next provider (live UI requests)."""
    import anyio
    import openai

    try:
        return await call()
    except openai.APIStatusError as exc:
        wait = _wait_seconds(exc)
        if wait is None or wait > max_wait:
            raise
        await anyio.sleep(wait)
        return await call()


# --------------------------------------------------------------------------- OpenAI-compatible (Groq, Gemini)
class OpenAICompatProvider:
    def __init__(self, name: str, client=None, model: str | None = None, max_wait: float = 30.0):
        base_url, key_env, model_env, default_model = OPENAI_COMPAT[name]
        self.name = name
        self.model = model or os.getenv(model_env, default_model)
        self.max_wait = max_wait  # longest rate-limit wait before giving up on this provider
        if client is None:
            from openai import AsyncOpenAI
            # no SDK retries when we may not wait: a 429 should fall through to the next provider at once
            client = AsyncOpenAI(api_key=os.getenv(key_env), base_url=base_url, max_retries=1 if max_wait else 0,
                                 timeout=60 if max_wait else 25)
        self.client = client

    @staticmethod
    def tool_defs(tools: list[dict]) -> list[dict]:
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                   "parameters": t["input_schema"]}} for t in tools]

    def user(self, text: str) -> dict:
        return {"role": "user", "content": text}

    async def turn(self, system: str, messages: list, tools: list[dict]) -> Turn:
        import openai

        try:
            resp = await _with_limit_retry(lambda: self.client.chat.completions.create(
                model=self.model, temperature=0.2,
                messages=[{"role": "system", "content": system}, *messages],
                tools=self.tool_defs(tools), tool_choice="auto",
            ), self.max_wait)
        except (openai.APIStatusError, openai.APIConnectionError) as exc:  # 413/429/5xx/auth/timeouts: try the next provider
            raise ProviderUnavailable(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            calls.append(Call(id=tc.id, name=tc.function.name, args=args, raw_args=tc.function.arguments or ""))
        assistant = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            # Echo each tool call exactly as received: Gemini puts a required thought signature in
            # tool_calls[].extra_content.google.thought_signature and rejects the next turn without it.
            assistant["tool_calls"] = [_dump(tc) for tc in msg.tool_calls]
        note = (msg.content or "").strip() or (getattr(msg, "reasoning", None) or "").strip()  # reasoning models
        usage = getattr(resp, "usage", None)
        return Turn(text=note if calls else (msg.content or "").strip(), calls=calls, assistant_message=assistant,
                    model=f"{self.name}:{resp.model}", tokens=getattr(usage, "total_tokens", 0) or 0)

    def tool_results(self, results: list[tuple[Call, str, bool]]) -> list[dict]:
        # one tool message per call; Groq rejects messages[].name, so it is not sent
        return [{"role": "tool", "tool_call_id": call.id, "content": text} for call, text, _ in results]

    async def complete(self, system: str, user: str) -> tuple[str, str]:
        """Plain completion, no tools (used by the eval's flat baseline). Returns (text, model)."""
        import openai

        try:
            resp = await _with_limit_retry(lambda: self.client.chat.completions.create(
                model=self.model, temperature=0.2,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}]), self.max_wait)
        except (openai.APIStatusError, openai.APIConnectionError) as exc:
            raise ProviderUnavailable(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        self.last_tokens = getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0
        return (resp.choices[0].message.content or "").strip(), f"{self.name}:{resp.model}"

    async def json(self, system: str, user: str) -> tuple[str, str]:
        """JSON-mode completion (used by ingestion). Returns (text, model)."""
        import openai

        try:
            resp = await _with_limit_retry(lambda: self.client.chat.completions.create(
                model=self.model, temperature=0.1, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            ), self.max_wait)
        except (openai.APIStatusError, openai.APIConnectionError) as exc:  # 413/429/5xx/auth/timeouts: try the next provider
            raise ProviderUnavailable(f"{self.name}: {type(exc).__name__}: {exc}") from exc
        return resp.choices[0].message.content or "", f"{self.name}:{resp.model}"


# --------------------------------------------------------------------------- Anthropic (optional)
class AnthropicProvider:
    BETAS = ["server-side-fallback-2026-07-01", "thinking-display-updates-2026-08-18"]

    def __init__(self, client=None, model: str | None = None):
        self.name = "anthropic"
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        if client is None:
            import anthropic
            client = anthropic.AsyncAnthropic()
        self.client = client

    def user(self, text: str) -> dict:
        return {"role": "user", "content": text}

    async def turn(self, system: str, messages: list, tools: list[dict]) -> Turn:
        try:
            import anthropic
            errors = (anthropic.RateLimitError, anthropic.AuthenticationError, anthropic.APIConnectionError,
                      anthropic.InternalServerError, anthropic.PermissionDeniedError)
        except ImportError:  # pragma: no cover
            errors = ()
        try:
            response = await self.client.beta.messages.create(
                model=self.model, max_tokens=16000, betas=self.BETAS, fallbacks="default",
                thinking={"type": "adaptive", "display": "updates"}, output_config={"effort": "medium"},
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=tools, messages=messages,
            )
        except errors as exc:
            raise ProviderUnavailable(f"anthropic: {type(exc).__name__}: {exc}") from exc
        if response.stop_reason == "refusal":
            raise ProviderUnavailable("anthropic: request declined by a safety classifier")
        calls = [Call(id=b.id, name=b.name, args=b.input) for b in response.content if b.type == "tool_use"]
        notes = [getattr(b, "thinking", "") or "" for b in response.content if b.type == "thinking"]
        texts = [b.text for b in response.content if b.type == "text"]
        text = " ".join(t.strip() for t in (notes + texts if calls else texts) if t and t.strip())
        return Turn(text=text, calls=calls, assistant_message={"role": "assistant", "content": response.content},
                    model=f"anthropic:{response.model}")

    def tool_results(self, results: list[tuple[Call, str, bool]]) -> list[dict]:
        # all results in ONE user message
        return [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": c.id, "content": text, **({"is_error": True} if err else {})}
            for c, text, err in results]}]


# --------------------------------------------------------------------------- rules (no model)
SERVICE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")
ID_RE = re.compile(r"\b(?:per|svc|inc|adr|team):[a-z0-9-]+\b")


class RulesProvider:
    """Deterministic planner for when no model is reachable. It still calls tools over MCP; it just
    chooses them with keyword rules instead of a model, and says so in its answer."""

    def __init__(self):
        self.name, self.model = "rules", "rules"
        self.planned = False

    def user(self, text: str) -> dict:
        return {"role": "user", "content": text}

    @staticmethod
    def plan(question: str) -> list[tuple[str, dict]]:
        q = question.lower()
        ids = ID_RE.findall(q)
        services = [s for s in SERVICE_RE.findall(q) if not s.startswith(("on-call", "single-point"))]
        svc = services[0] if services else None
        # counterfactuals: "if Priya Nair leaves", "if Team Ledger is dissolved", "if we decommission pdf-renderer-v1"
        if m := re.search(r"if ([a-z][a-z .'-]+?) (?:leaves|left|quits|resigns)", q):
            return [("what_if", {"scenario": "person_leaves", "entity": m.group(1).strip()})]
        if m := re.search(r"if (?:team )?([a-z][a-z-]+) (?:is |was |were )?(?:dissolved|disbanded)", q):
            return [("what_if", {"scenario": "team_dissolved", "entity": m.group(1)})]
        if m := re.search(r"decommission(?:ed)? ([a-z][a-z0-9-]+)|if ([a-z][a-z0-9-]+) (?:is |was )?decommissioned", q):
            return [("what_if", {"scenario": "service_decommissioned", "entity": m.group(1) or m.group(2)})]
        incident = next((i for i in ids if i.startswith("inc:")), None)
        if incident and re.search(r"hand ?off|escalate|remediat", q) and not q.startswith("handoff "):
            return [("handoff", {"incident": incident, "summary": question[:300], "request": "Investigate and propose a fix."})]
        if q.startswith("handoff ") and SERVICE_RE.search(q.split("affected:")[-1]):
            svc_h = SERVICE_RE.findall(q.split("affected:")[-1])[0].removeprefix("svc:")
            return [("recall", {"entities": [f"svc:{svc_h}"]}), ("decision_trail", {"service": svc_h}),
                    ("propose_action", {"kind": "create_ticket", "target": svc_h,
                                        "reason": "Follow-up from handoff (rules mode)", "title": f"Follow up {incident or svc_h}"})]
        if len(ids) >= 2 or (re.search(r"\b(connected|path|between|link)\b", q) and len(ids + services) >= 2):
            a, b = (ids + services)[:2]
            return [("shortest_path", {"from": a, "to": b, "mode": "any" if ":" in a + b else "dependency"})]
        if re.search(r"single points? of (knowledge|failure)|key people|bus factor|knowledge silo", q):
            return [("key_people", {})]
        if re.search(r"orphan|unowned|no owner|nobody owns", q):
            return [("find_orphans", {})]
        if re.search(r"most (critical|important)|critical services", q):
            return [("critical_services", {})]
        if not svc:
            return []
        if re.search(r"\b(retry|change|modify|allowed|can we|decision|adr)\b", q):
            action = "change_retry_policy" if "retry" in q else None
            return [("decision_trail", {"service": svc, **({"action": action} if action else {})})]
        if re.search(r"fail|down|outage|broken|timeout|error|slow|latency|affected|blast", q):
            return [("blast_radius", {"service": svc}), ("similar_incidents", {"service": svc}),
                    ("recall", {"entities": [f"svc:{svc}"]})]
        if re.search(r"on[ -]?call|page|pager", q):
            return [("why_not", {"kind": "on_call", "service": svc})]
        if re.search(r"who knows|expert|knowledge|single point", q):
            return [("who_knows", {"service": svc})]
        if re.search(r"own|owner|team", q):
            return [("owner_of", {"service": svc, "include_history": True})]
        if re.search(r"similar|before|seen|prior|history", q):
            return [("similar_incidents", {"service": svc})]
        return [("owner_of", {"service": svc}), ("blast_radius", {"service": svc})]

    async def turn(self, system: str, messages: list, tools: list[dict]) -> Turn:
        if not self.planned:
            self.planned = True
            question = next(m["content"] for m in reversed(messages) if m["role"] == "user" and isinstance(m["content"], str))
            plan = self.plan(question)
            if plan:
                calls = [Call(id=f"r{i}", name=n, args=a) for i, (n, a) in enumerate(plan)]
                return Turn(text="Rules mode: tools chosen by keyword rules (no model available).", calls=calls,
                            assistant_message={"role": "assistant", "content": "", "rules_calls": plan}, model="rules")
            return Turn(text="Rules mode (no model available): I could not find a service or entity id in the question. "
                             "Try naming one, e.g. payments-api or per:priya-nair.", model="rules")
        explanations = []
        for m in messages:
            if m.get("role") == "tool":
                try:
                    explanations.append(json.loads(m["content"]).get("explanation", ""))
                except (json.JSONDecodeError, AttributeError):
                    explanations.append(m["content"])
        answer = "Rules mode (no model available), straight from the graph tools:\n- " + "\n- ".join(e for e in explanations if e)
        return Turn(text=answer, model="rules")

    def tool_results(self, results: list[tuple[Call, str, bool]]) -> list[dict]:
        return [{"role": "tool", "tool_call_id": c.id, "content": text} for c, text, _ in results]


# --------------------------------------------------------------------------- selection
def available(name: str) -> bool:
    if name in OPENAI_COMPAT:
        return bool(os.getenv(OPENAI_COMPAT[name][1]))
    if name == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    return name == "rules"


def provider_order(include_rules: bool = True) -> list[str]:
    names = [n.strip() for n in os.getenv("TRIVENI_LLM_PROVIDERS", DEFAULT_ORDER).split(",") if n.strip()]
    if include_rules and "rules" not in names:
        names.append("rules")
    return [n for n in names if available(n) and (include_rules or n != "rules")]


def make(name: str, max_wait: float = 30.0):
    """max_wait: longest rate-limit wait per call (s). The UI passes 0 so a limited provider falls through at once."""
    if name in OPENAI_COMPAT:
        return OpenAICompatProvider(name, max_wait=max_wait)
    if name == "anthropic":
        return AnthropicProvider()
    if name == "rules":
        return RulesProvider()
    raise ValueError(f"unknown provider {name!r}")
