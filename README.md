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
```

## Graph model
One FalkorDB graph per tenant (`tenant_<name>`). Full model: [notes/graph-model.md](notes/graph-model.md).

_TODO: diagram + node/edge tables._

## Track 01: Act on connected data
| Key focus | Feature |
|---|---|
| Multi-hop reasoning | _TODO_ |
| Graph queries and algorithms as agent tools | _TODO_ |
| Tool selection through MCP | _TODO_ |
| Actions based on what the graph shows | _TODO_ |
| Explainable results | _TODO_ |

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
| Knowledge from docs, tickets, chats in one graph | _TODO_ |
| Who owns what, who knows what | _TODO_ |
| Tracing decisions to source | _TODO_ |
| Keeping knowledge current | Temporal State edges (`valid_from`/`valid_to`, `source_doc`) |
| Answers with clear sources | _TODO_ |

## Cypher and algorithms used
See [docs/queries.md](docs/queries.md). Every query is listed with its track and where it is used.

## Eval
_TODO: per-track table, graph agent vs flat TF-IDF baseline._

## Data
All data is synthetic, produced by a deterministic generator (`backend/scripts/seed.py`). No private, login-gated, or personal data.

## AI usage
This project was built with AI assistance (Claude Code) for code generation and review. The team designed the graph model and can explain every query, the model, and the architecture.
