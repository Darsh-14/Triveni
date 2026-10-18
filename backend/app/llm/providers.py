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
                                 timeout=60 if max_wait else 20)
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
            raise ProviderUnavailable(f"{self.name}: {type(exc).__name__} ({self.model}): {exc}") from exc
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
            raise ProviderUnavailable(f"{self.name}: {type(exc).__name__} ({self.model}): {exc}") from exc
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
            raise ProviderUnavailable(f"{self.name}: {type(exc).__name__} ({self.model}): {exc}") from exc
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
PREFIX_LABEL = {"per": "Person", "svc": "Service", "inc": "Incident", "adr": "Decision", "team": "Team"}


class RulesProvider:
    """Deterministic planner for when no model is reachable. It still calls tools over MCP; it just chooses them with
    rules instead of a model, and says so in its answer.

    Entities come from the tenant's graph (graph/resolve.spot: "Payments API", "Priya", "Team Ledger", "incident 42",
    "ADR-019"), not from a slug regex, so plain phrasing works. Intent comes from keywords, checked from most specific
    (counterfactual, handoff, two-entity connection) to least specific (describe the one entity named). Every argument
    is still resolved again by the tool layer, so a wrong guess becomes an explicit unknown_entity, never a fake answer.
    """

    ACTIONS = (("retry", "change_retry_policy"), ("timeout", "raise_timeout"), ("rerun", "rerun_without_reconciliation"))

    def __init__(self, tenant: str | None = None):
        self.name, self.model = "rules", "rules"
        self.tenant = tenant  # set by the agent loop: enables spotting entities by name in the graph
        self.planned = False

    def user(self, text: str) -> dict:
        return {"role": "user", "content": text}

    @staticmethod
    def _regex_entities(question: str) -> list[dict]:
        """Fallback without a graph: typed ids and service-like slugs."""
        q = question.lower()
        found = [{"id": i, "label": PREFIX_LABEL.get(i.split(":")[0], "?"), "name": i} for i in ID_RE.findall(q)]
        named = {e["id"].split(":", 1)[1] for e in found}
        found += [{"id": f"svc:{s}", "label": "Service", "name": s} for s in SERVICE_RE.findall(q)
                  if not s.startswith(("on-call", "single-point")) and s not in named]
        return found

    @classmethod
    def plan(cls, question: str, entities: list[dict] | None = None) -> list[tuple[str, dict]]:
        q = question.lower()
        ents = entities if entities is not None else cls._regex_entities(question)
        of = lambda *labels: [e for e in ents if e["label"] in labels]  # noqa: E731
        svcs, people, teams = of("Service"), of("Person"), of("Team")
        incidents, decisions = of("Incident"), of("Decision")
        svc = svcs[0]["id"].removeprefix("svc:") if svcs else None

        # 1. counterfactuals: "if Priya Nair leaves", "if Team Ledger is dissolved", "if we decommission pdf-renderer-v1"
        if re.search(r"\b(leaves|left|quits|resigns|leaving)\b", q):
            who = people[0]["id"] if people else (m.group(1).strip() if (m := re.search(r"if ([a-z][a-z .'-]+?) (?:leaves|left|quits|resigns)", q)) else None)
            if who:
                return [("what_if", {"scenario": "person_leaves", "entity": who})]
        if re.search(r"\b(dissolved|disbanded|dissolve|disband)\b", q):
            team = teams[0]["id"] if teams else (m.group(1) if (m := re.search(r"if (?:team )?([a-z][a-z-]+) (?:is |was |were )?(?:dissolved|disbanded)", q)) else None)
            if team:
                return [("what_if", {"scenario": "team_dissolved", "entity": team})]
        if re.search(r"decommission", q):
            target = svc or (m.group(1) or m.group(2) if (m := re.search(r"decommission(?:ed)? ([a-z][a-z0-9-]+)|if ([a-z][a-z0-9-]+) (?:is |was )?decommissioned", q)) else None)
            if target:
                return [("what_if", {"scenario": "service_decommissioned", "entity": target})]

        # 2. coordination: hand an incident to remediation; the remediation agent's own "handoff ..." follow-up
        incident = incidents[0]["id"] if incidents else None
        if incident and re.search(r"hand ?off|escalate|remediat", q) and not q.startswith("handoff "):
            return [("handoff", {"incident": incident, "summary": question[:300], "request": "Investigate and propose a fix."})]
        if q.startswith("handoff ") and SERVICE_RE.search(q.split("affected:")[-1]):
            svc_h = SERVICE_RE.findall(q.split("affected:")[-1])[0].removeprefix("svc:")
            return [("recall", {"entities": [f"svc:{svc_h}"]}), ("decision_trail", {"service": svc_h}),
                    ("propose_action", {"kind": "create_ticket", "target": svc_h,
                                        "reason": "Follow-up from handoff (rules mode)", "title": f"Follow up {incident or svc_h}"})]

        # 3. two entities: does A depend on B (current edges, with an absence proof), or how are they connected
        if len(ents) >= 2 and (re.search(r"\b(connected|connection|path|between|link|linked|related|relate)\b", q)
                               or (re.search(r"\bdepend", q) and len(svcs) >= 2)):
            a, b = ents[0], ents[1]
            if re.search(r"\bdepend", q) and a["label"] == b["label"] == "Service":
                return [("why_not", {"kind": "depends", "service": a["id"].removeprefix("svc:"),
                                     "other": b["id"].removeprefix("svc:")})]
            return [("shortest_path", {"from": a["id"], "to": b["id"], "mode": "any"})]

        # 3b. recency and approvals ("who approved the most recent change?", "latest deploy on payments-api",
        #     "recent SEV1s", "what is waiting for approval?"); "last time X failed" is about memory, not recency
        scope = {"service": svc} if svc else {}
        recency = re.search(r"\b(recent|recently|latest|newest|lately|today|this week|what changed|what's changed)\b"
                            r"|\blast\b(?!\s+time)", q)
        if re.search(r"\bapprov|awaiting|waiting for|pending", q):
            return [("recent", {"kind": "actions", **scope})] + (
                [("recent", {"kind": "deployments", **scope})] if re.search(r"\bchange", q) else [])
        if re.search(r"\bhandoffs?\b|hand-offs?", q) and not incident:
            return [("list_handoffs", {"status": "open" if "open" in q else "done" if re.search(r"\bdone|finished|completed", q) else "claimed" if "claimed" in q else "open"})]
        if recency:
            kinds = [k for k, pat in (("deployments", r"deploy|release|ship|roll|change|version"),
                                      ("incidents", r"incident|outage|sev\s?\d|page[sd]?\b|broke"),
                                      ("decisions", r"decision|adr|policy"),
                                      ("actions", r"action|ticket|notif|proposal|change")) if re.search(pat, q)]
            if kinds or not ents:
                return [("recent", {"kind": k, **scope}) for k in (kinds or ["deployments", "incidents"])]

        # 4. whole-graph algorithms
        if re.search(r"single points? of (knowledge|failure)|key people|bus factor|knowledge silo", q):
            return [("key_people", {})]
        if re.search(r"orphan|unowned|no owner|nobody owns|without (an )?owner", q):
            return [("find_orphans", {})]
        if re.search(r"most (critical|important)|critical services|riskiest", q):
            return [("critical_services", {})]

        # 5. one decision or incident: everything the graph states about it, with sources
        if decisions and not svc:
            return [("describe", {"entity": decisions[0]["id"]})]
        if incident:
            plan = [("describe", {"entity": incident})]
            if re.search(r"similar|before|seen|prior|again|history", q):
                plan.append(("similar_incidents", {"incident": incident}))
            return plan

        # 6. one service
        if svc:
            action = next((a for word, a in cls.ACTIONS if word in q), None)
            if action or re.search(r"\b(change|modify|allowed|can we|safe to|decision|decisions|adr|govern|governs|policy)\b", q):
                return [("decision_trail", {"service": svc, **({"action": action} if action else {})})]
            if re.search(r"fail|down|outage|broken|error|slow|latency|affected|blast|break|impact|incident", q):
                return [("blast_radius", {"service": svc}), ("similar_incidents", {"service": svc}),
                        ("recall", {"entities": [f"svc:{svc}"]})]
            if re.search(r"on[ -]?call|\bpage\b|pager", q):
                return [("why_not", {"kind": "on_call", "service": svc})]
            if re.search(r"who knows|expert|knowledge|ask about|who to ask|who should i ask", q):
                return [("who_knows", {"service": svc})]
            if re.search(r"\bown|owner|team|responsible", q):
                return [("owner_of", {"service": svc, "include_history": True})]
            if re.search(r"similar|before|seen|prior|history|last time|learn", q):
                return [("similar_incidents", {"service": svc}), ("recall", {"entities": [f"svc:{svc}"]})]
            return [("describe", {"entity": f"svc:{svc}"})]

        # 7. one team or person: what they own, who is in it / what they work on, know and are on call for
        if teams:
            return [("describe", {"entity": teams[0]["id"]})]
        if people:
            return [("describe", {"entity": people[0]["id"]})]
        # 8. nothing in the graph matched, but something looks like a name ("paymnts-api", "inc:9999"): let the
        #    resolver answer, so the reply is an explicit unknown_entity with suggestions, not silence
        if near := [e for e in ents if e["label"] == "near_miss"]:
            return [("describe", {"entity": near[0]["id"]})]
        return []

    def _entities(self, question: str) -> list[dict] | None:
        if not self.tenant:
            return None
        from backend.app.graph.resolve import SPOT_LABELS, Catalog, spot, suggestions  # lazy: no database at import
        from backend.app.graph.tenant import get_graph

        graph = get_graph(self.tenant)
        catalog = Catalog.load(graph, SPOT_LABELS)
        found = spot(graph, question, catalog)
        if found:
            return found
        # nothing matched: a typed id ("inc:9999") or a token close to a real name ("paymnts-api") is a near miss
        # worth an explicit unknown_entity answer; ordinary hyphenated words ("tier-1", "on-call") are not
        q = question.lower()
        near = ID_RE.findall(q) + [t for t in SERVICE_RE.findall(q) if suggestions(t, catalog.rows)]
        return [{"id": t, "label": "near_miss", "name": t, "text": t} for t in near[:1]]

    async def turn(self, system: str, messages: list, tools: list[dict]) -> Turn:
        if not self.planned:
            self.planned = True
            question = next(m["content"] for m in reversed(messages) if m["role"] == "user" and isinstance(m["content"], str))
            ents = self._entities(question)
            plan = self.plan(question, ents)
            if plan:
                calls = [Call(id=f"r{i}", name=n, args=a) for i, (n, a) in enumerate(plan)]
                named = ", ".join(f"{e['text']} -> {e['id']}" for e in ents or [])
                return Turn(text="Rules mode: tools chosen by deterministic rules (no model available)"
                                 + (f"; entities found in the graph: {named}." if named else "."), calls=calls,
                            assistant_message={"role": "assistant", "content": "", "rules_calls": plan}, model="rules")
            return Turn(text="Rules mode (no model available): the question names no service, person, team, incident or "
                             "decision in this graph, so nothing was looked up. Name one, by name or id.", model="rules")
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


# --------------------------------------------------------------------------- chain + cooldown (live requests)
# Free tiers limit each model separately, so one provider name can offer several models. Live requests try them in
# order and skip any model that failed moments ago, instead of paying its timeout again on every question.
EXTRA_MODELS = {"groq": ("openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b")}
COOLDOWN_S = {"quota": 900, "not_found": 3600, "timeout": 120, "rate": 60, "other": 60}
_cooling: dict[str, float] = {}  # "groq/openai/gpt-oss-120b" -> monotonic time it may be tried again


def models_for(name: str) -> list[str]:
    """TRIVENI_<NAME>_MODELS (comma list) if set, else the configured model followed by the extra free-tier models."""
    _, _, model_env, default = OPENAI_COMPAT[name]
    listed = os.getenv(f"TRIVENI_{name.upper()}_MODELS")
    if listed:
        return [m.strip() for m in listed.split(",") if m.strip()]
    first = os.getenv(model_env, default)
    return [first] + [m for m in EXTRA_MODELS.get(name, ()) if m != first]


def _key(provider) -> str:
    return f"{provider.name}/{getattr(provider, 'model', '')}"


def cool_down(provider, error: str) -> None:
    """Remember that this model just failed, for long enough that the next questions skip it."""
    import time

    e = error.lower()
    kind = ("quota" if "per day" in e or "quota" in e or "tokens per d" in e else "not_found" if "404" in e
            else "timeout" if "timed out" in e or "timeout" in e else "rate" if "429" in e or "rate" in e else "other")
    _cooling[_key(provider)] = time.monotonic() + COOLDOWN_S[kind]


def make_chain(max_wait: float = 30.0) -> list:
    """Every available provider and model, in order, minus the ones cooling down. Rules is always last."""
    import time

    now, chain = time.monotonic(), []
    for name in provider_order():
        if name in OPENAI_COMPAT:
            chain += [OpenAICompatProvider(name, model=m, max_wait=max_wait) for m in models_for(name)]
        else:
            chain.append(make(name, max_wait))
    return [p for p in chain if p.name == "rules" or _cooling.get(_key(p), 0) <= now]
