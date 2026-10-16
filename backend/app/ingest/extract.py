"""Read a raw document and extract entities + facts into the fixed schema with Claude.

The output schema (pydantic, enforced by structured outputs) only allows the labels and
fact types Triveni knows, so the model cannot invent new ones. merge.py validates again
against schema.py (endpoints, required properties) before anything is written.

Extractions are cached in data/extracted/<doc>.json. Re-ingesting reuses the cache, which
keeps ingestion reproducible and lets the demo run without the API (DEMO_REPLAY).
"""
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

CACHE_DIR = Path("data/extracted")

EntityLabel = Literal["Person", "Team", "Service", "Incident", "Decision"]
# Fact edges the model may extract. Document edges (WROTE, MENTIONS, EVIDENCE_FOR) are added by code.
FactType = Literal[
    "MEMBER_OF", "OWNS", "ON_CALL_FOR", "DEPENDS_ON",
    "AFFECTED", "RESOLVED", "MADE", "GOVERNS", "SUPERSEDES",
]


class Entity(BaseModel):
    ref: str = Field(description="The catalog id if the entity is in the catalog (e.g. svc:orders-api), otherwise a short new name")
    label: EntityLabel
    name: str = Field(description="Human-readable name (for incidents/decisions: the title)")
    role: str | None = Field(default=None, description="Person only: job role if stated")
    severity: str | None = Field(default=None, description="Incident only: SEV1/SEV2/SEV3 if stated")
    summary: str | None = Field(default=None, description="Incident or Decision only: one-sentence summary / rationale")
    forbids: list[str] = Field(default_factory=list, description="Decision only: action kinds it disallows, snake_case (e.g. change_timeout)")


class Fact(BaseModel):
    type: FactType
    src: str = Field(description="ref of the source entity")
    dst: str = Field(description="ref of the target entity")
    ends: bool = Field(default=False, description="true only if the document says this fact stopped being true")
    evidence: str = Field(description="short quote from the document supporting the fact")


class Extraction(BaseModel):
    entities: list[Entity]
    facts: list[Fact]


@dataclass
class RawDoc:
    id: str
    kind: str
    title: str
    ts: str
    author: str | None
    text: str
    source: str  # path, relative to the repo


def read_document(path: str | Path) -> RawDoc:
    """Markdown with a small `key: value` front matter block between --- lines."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw.replace("\r\n", "\n"), re.S)
    if not m:
        raise ValueError(f"{p}: missing front matter")
    meta = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    for key in ("id", "kind", "title", "ts"):
        if not meta.get(key):
            raise ValueError(f"{p}: front matter needs {key}")
    return RawDoc(id=meta["id"], kind=meta["kind"], title=meta["title"], ts=meta["ts"],
                  author=meta.get("author") or None, text=m.group(2).strip(), source=p.as_posix())


SYSTEM = """You extract facts from internal engineering documents into a fixed graph schema.

Entities: Person, Team, Service, Incident, Decision.
Fact types (src -> dst):
- MEMBER_OF: Person -> Team            (current team membership)
- OWNS: Team -> Service                (current owning team)
- ON_CALL_FOR: Person -> Service       (current on-call engineer)
- DEPENDS_ON: Service -> Service       (src calls / needs dst)
- AFFECTED: Incident -> Service
- RESOLVED: Person -> Incident
- MADE: Person -> Decision
- GOVERNS: Decision -> Service
- SUPERSEDES: Decision -> Decision     (newer -> older)

Rules:
- Only extract facts the document states. Never infer from general knowledge.
- Use the catalog id as `ref` whenever the entity appears in the catalog (match names case-insensitively;
  "ADR-019" is adr:019, "inc:0057" is inc:0057). Use a short new name only for entities not in the catalog.
- Every fact's src and dst must be the `ref` of an entity you list.
- A change ("moves from Team A to Team B", "taking over on-call") is ONE new fact (Team B / the new person).
  Do not emit the old fact; the system closes it. Use `ends: true` only when the document says a fact
  stopped without a replacement.
- Quote the supporting text in `evidence`."""


def catalog(graph) -> str:
    """Known entities the model should link to (ids + names), one line each, sorted for cache stability."""
    rows = graph.ro_query(
        "MATCH (n) WHERE n:Person OR n:Team OR n:Service OR n:Incident OR n:Decision "
        "RETURN labels(n)[0], n.id, coalesce(n.name, n.title) ORDER BY labels(n)[0], n.id"
    ).result_set
    return "\n".join(f"{label} {node_id} {name}" for label, node_id, name in rows)


def cache_path(doc_id: str) -> Path:
    return CACHE_DIR / (doc_id.replace(":", "-") + ".json")


def _user_prompt(doc: RawDoc) -> str:
    return (f"Document {doc.id} ({doc.kind}), written {doc.ts} by {doc.author or 'unknown'}.\n"
            f"Title: {doc.title}\n\n{doc.text}")


async def _extract_openai_compat(provider, doc: RawDoc, catalog_text: str) -> tuple[Extraction, str]:
    """JSON mode + pydantic validation; one retry that shows the model its validation error."""
    from pydantic import ValidationError

    system = (SYSTEM + "\n\nReturn ONLY a JSON object that matches this JSON Schema:\n"
              + json.dumps(Extraction.model_json_schema()) + "\n\nCatalog (label id name):\n" + catalog_text)
    user = _user_prompt(doc)
    for attempt in range(2):
        text, model = await provider.json(system, user)
        try:
            return Extraction.model_validate_json(text), model
        except ValidationError as err:
            if attempt:
                raise
            user = _user_prompt(doc) + f"\n\nYour previous JSON was invalid: {err.errors()[:3]}. Return corrected JSON only."
    raise AssertionError("unreachable")


def _extract_anthropic(doc: RawDoc, catalog_text: str) -> tuple[Extraction, str]:
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"), max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default", output_config={"effort": "medium"},
        system=[{"type": "text", "text": SYSTEM},
                {"type": "text", "text": "Catalog (label id name):\n" + catalog_text, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": _user_prompt(doc)}],
        output_format=Extraction,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"extraction refused for {doc.id}")
    return response.parsed_output, f"anthropic:{response.model}"


def extract(doc: RawDoc, graph, refresh: bool = False) -> tuple[Extraction, str]:
    """Return (extraction, origin): origin is 'cache' or the provider:model that produced it.
    Providers are tried in TRIVENI_LLM_PROVIDERS order; the first valid extraction wins and is cached."""
    import anyio

    from backend.app.llm.providers import ProviderUnavailable, make, provider_order

    path = cache_path(doc.id)
    if path.exists() and not refresh:
        return Extraction.model_validate_json(path.read_text(encoding="utf-8")), "cache"
    if os.getenv("DEMO_REPLAY") == "1":
        raise RuntimeError(f"DEMO_REPLAY=1 and no cached extraction for {doc.id}")

    catalog_text = catalog(graph)
    errors = []
    for name in provider_order(include_rules=False):
        try:
            if name == "anthropic":
                extraction, origin = _extract_anthropic(doc, catalog_text)
            else:
                extraction, origin = anyio.run(_extract_openai_compat, make(name), doc, catalog_text)
            break
        except (ProviderUnavailable, ValueError, RuntimeError) as exc:  # ValidationError is a ValueError
            errors.append(f"{name}: {str(exc)[:200]}")
    else:
        raise RuntimeError("no model could extract " + doc.id + (": " + "; ".join(errors) if errors else
                           " (set GROQ_API_KEY or GEMINI_API_KEY in .env)"))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**extraction.model_dump(), "_model": origin}, indent=2) + "\n", encoding="utf-8")
    return extraction, origin
