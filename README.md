# Triveni

**त्रिवेणी, "the confluence of three."** An engineering Company Brain on [FalkorDB](https://www.falkordb.com/) where agents **act** on connected data, **remember and coordinate** through the graph, and **prove every answer with a path**.

Built for **Graph Hacks: Context for AI Agents** (WeMakeDevs × FalkorDB). Tracks entered:
- Track 01: Agents That Act on Connected Data
- Track 02: Agent Memory and Coordination
- Track 03: Company Brain

> Status: in progress during the event window (Oct 15–18, 2026).

## Why a graph
Incident questions are about connections: what depends on this service, who owns it, what changed, which decision constrains us, who fixed this before. Each one is a traversal, and none is a text lookup. Every Triveni answer includes the Cypher it ran, the path it found, and the source documents behind it.

## Setup
```bash
docker compose up -d falkordb                      # or use FalkorDB Cloud, see .env.example
python -m venv .venv && . .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
python -m backend.scripts.seed --tenant acme --seed 42
python -m backend.scripts.seed --tenant beta --seed 7
pytest -q
uvicorn backend.app.main:app --reload            # API on :8000
npm --prefix frontend install && npm --prefix frontend run dev   # UI on :3001
python -m backend.app.agents.triage "payments-api is failing, what's affected and who do I page?" --tenant acme
```

## Graph model
One FalkorDB graph per tenant (`tenant_<name>`). Full model: [notes/graph-model.md](notes/graph-model.md).

_TODO: diagram + node/edge tables._

## Track 01: Act on connected data
| Key focus | Feature |
|---|---|
| Multi-hop reasoning | `blast_radius` (variable-length DEPENDS_ON, current edges only, with owners and on-call), `shortest_path` (dependency chains or any fact path, e.g. person → incident → service → service), `decision_trail` (SUPERSEDES chains) |
| Graph queries and algorithms as agent tools | _TODO_ |
| Tool selection through MCP | `backend/app/mcp_server.py` exposes the whole registry over MCP, one server per tenant (the tenant is never a tool argument). The triage agent (`agents/triage.py`) lists tools over MCP and calls them over MCP; every step is logged with tool, input, the model's progress note (why) and timing |
| Actions based on what the graph shows | _TODO_ |
| Explainable results | Every MCP tool result carries `cypher`, `params`, `paths`, `sources`, `tracks` as structuredContent; the agent cites entity ids and source documents |

## Track 02: Remember & coordinate
| Key focus | Feature |
|---|---|
| Episodic, semantic, procedural memory | _TODO_ |
| Persistent conversation history | _TODO_ |
| Shared state and handoffs | _TODO_ |
| High-concurrency reads and writes | _TODO_ |
| Separate memory per user or tenant | One graph per tenant; isolation test (`backend/tests/test_isolation.py`) |

## Track 03: Company Brain
| Key focus | Feature |
|---|---|
| Knowledge from docs, tickets, chats in one graph | `ingest_document`: LLM extraction into the fixed schema (unknown types impossible by output schema, invalid endpoints rejected), MERGE with `source_doc` on every edge (`backend/app/ingest/`) |
| Who owns what, who knows what | `owner_of` (current owner + on-call with sources, optional history); `who_knows` (people ranked by evidence: resolved incidents, deploys, decisions, docs, on-call, each with its path); `why_not` (absence proof, e.g. no on-call for billing-batch, plus who to contact instead) |
| Tracing decisions to source | `decision_trail`: SUPERSEDES chain → GOVERNS → EVIDENCE_FOR source ADRs; flags runbooks that still cite a superseded decision; checks whether an action is forbidden |
| Keeping knowledge current | Temporal State edges (`valid_from`/`valid_to`/`ended_by`): a contradicting fact closes the old edge and creates the new one; history is never deleted (`ingest/temporal.py`) |
| Answers with clear sources | Every tool returns `sources` (Document ids taken from `source_doc` on the edges it used), plus `cypher`, `params` and `paths` (provenance contract, `tools/base.py`) |

## Cypher and algorithms used
See [docs/queries.md](docs/queries.md). Every query is listed with its track and where it is used.

## Eval
_TODO: per-track table, graph agent vs flat TF-IDF baseline._

## Data
All data is synthetic, produced by a deterministic generator (`backend/scripts/seed.py`). No private, login-gated, or personal data.

## AI usage
This project was built with AI assistance (Claude Code) for code generation and review. The team designed the graph model and can explain every query, the model, and the architecture.

At runtime, the triage agent and document extraction use free-tier models through one provider interface: Groq (`qwen/qwen3.8-27b`) first, Gemini (`gemini-3.8-flash`) as fallback, and a no-model keyword planner (`rules`) as the last resort, so the demo cannot fail on a rate limit. Every tool call goes over MCP regardless of provider. Document extractions are cached in `data/extracted/`.
