# Triveni

**त्रिवेणी, "the confluence of three."** An engineering Company Brain on [FalkorDB](https://www.falkordb.com/) where agents **act** on connected data, **remember and coordinate** through the graph, and **prove every answer with a path**.

Built for **Graph Hacks: Context for AI Agents** (WeMakeDevs × FalkorDB). Tracks entered:
- Track 01: Agents That Act on Connected Data
- Track 02: Agent Memory and Coordination
- Track 03: Company Brain

> Status: in progress during the event window (Oct 15–18, 2026).

## Why a graph
Incident questions are about connections: what depends on this service, who owns it, what changed, which decision constrains us, who fixed this before. Each one is a traversal, and none is a text lookup. Every Triveni answer includes the Cypher it ran, the path it found, and the source documents behind it.

## Interface
One screen, laid out after tools engineers already use. Left: the thread, where every answer shows a verdict from the deterministic proof check, its source documents as cards, the answer with every cited id as a clickable chip, and the tool result as structured fields (who to page, decision chain, recalled episode, what changed, action awaiting approval). Centre: the evidence subgraph on a Cytoscape canvas (Force / Tree / Radial layouts, label and relationship filters, search, Dim, Graph | Table views). Right: node properties with current and historical edges, the Cypher and parameters of each step, the source document, and the approvals inbox. Clicking a step highlights only that step's path.

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
| What-if simulation | `what_if`: "what if Priya leaves / Team Ledger is dissolved / pdf-renderer-v1 is decommissioned": the graph is cloned with FalkorDB `GRAPH.COPY`, the change is applied to the clone, algorithms rerun, and the diff is returned (knowledge lost, new single points of knowledge, new orphans, dependents) |
| Multi-hop reasoning | `blast_radius` (variable-length DEPENDS_ON, current edges only, with owners and on-call), `shortest_path` (dependency chains or any fact path, e.g. person → incident → service → service), `decision_trail` (SUPERSEDES chains) |
| Graph queries and algorithms as agent tools | `critical_services` (`algo.pageRank` on DEPENDS_ON), `key_people` (`algo.betweenness` on the derived expertise graph: single points of knowledge), `find_orphans` (`algo.WCC` on the derived responsibility graph), all exposed over MCP and checked against independently computed ground truth |
| Tool selection through MCP | `backend/app/mcp_server.py` exposes the whole registry over MCP, one server per tenant (the tenant is never a tool argument). The triage agent (`agents/triage.py`) lists tools over MCP and calls them over MCP; every step is logged with tool, input, the model's progress note (why) and timing |
| Actions based on what the graph shows | `propose_action` → Action node; blocked with a BLOCKED_BY edge when a current governing Decision forbids it (e.g. `change_retry_policy` on orders-api blocked by ADR-019); otherwise a person approves or rejects in the UI and approved actions go to a simulated outbox |
| Explainable results | Every MCP tool result carries `cypher`, `params`, `paths`, `sources`, `tracks` as structuredContent, plus an explicit `outcome` (answered / from memory / not in graph / unknown entity) so an empty traversal never reads as "nothing is affected"; the agent cites entity ids and source documents; a **deterministic proof check** (code, not a model) checks every entity the answer names, by id or by plain name, against the graph and this run's tool results, and catches invented services and people. **An answer that names anything a tool did not return is rejected and replaced by the tool results** (the draft stays inspectable) |
| Deterministic guardrails | Every entity argument is resolved against the graph before a tool runs (`graph/resolve.py`): "Payments API", "Team Ledger", "incident 42", "ADR 19" and a unique "Priya" resolve; near-misses like "paymnts-api" are refused with suggestions, never guessed; ambiguous names are refused with candidates. With no model reachable, a rules planner spots entities in the question from the graph itself and picks tools deterministically (27/27 test phrasings), so the product keeps answering on free-tier outages |

## Track 02: Remember & coordinate
| Key focus | Feature |
|---|---|
| Episodic, semantic, procedural memory | `remember` writes Episode (INVOLVED entities, RAN by the agent), Lesson (reinforced, not duplicated) and Procedure (success/fail counters); `recall` finds past episodes **through shared graph entities**: a new payments-api incident reaches last month's episode via `svc:payments-api`. Memory decays: lesson confidence halves every 90 days since last reinforced (computed on read, nothing deleted), and a failed procedure weakens the lessons learned with it |
| Persistent conversation history | Conversation -HAS_MESSAGE-> Message chained by NEXT; every request rebuilds the model's context from the graph (no in-process state, tested with a real process restart); the UI reopens any conversation |
| Shared state and handoffs | Triage and Remediation run as separate agents with separate MCP servers and share only graph state: Handoff nodes (open → claimed → done) with an atomic single-statement claim (8 concurrent claimers → 1 winner, tested) |
| High-concurrency reads and writes | `python -m backend.app.coordination.concurrency`: 16 agents on two tenants at once, 400 remember/recall/handoff/history operations in 5.3 s, p95 < 115 ms per operation to FalkorDB Cloud, 0 cross-tenant reads, 0 double claims, 0 duplicate message seq ([docs/concurrency.md](docs/concurrency.md)) |
| Separate memory per user or tenant | One graph per tenant; isolation test (`backend/tests/test_isolation.py`) |

## Track 03: Company Brain
| Key focus | Feature |
|---|---|
| Knowledge from docs, tickets, chats in one graph | `ingest_document`: LLM extraction into the fixed schema (unknown types impossible by output schema, invalid endpoints rejected), MERGE with `source_doc` on every edge (`backend/app/ingest/`) |
| Who owns what, who knows what | `describe` (everything the graph states about one incident, person, team or decision, current facts first, ended facts as history, superseded decisions labelled, each with its source); `owner_of` (current owner + on-call with sources, optional history); `who_knows` (people ranked by evidence: resolved incidents, deploys, decisions, docs, on-call, each with its path); `why_not` (absence proof, e.g. no on-call for billing-batch, plus who to contact instead) |
| Tracing decisions to source | `decision_trail`: SUPERSEDES chain → GOVERNS → EVIDENCE_FOR source ADRs; flags runbooks that still cite a superseded decision; checks whether an action is forbidden |
| Keeping knowledge current | Temporal State edges (`valid_from`/`valid_to`/`ended_by`): a contradicting fact closes the old edge and creates the new one; history is never deleted (`ingest/temporal.py`). **Change impact:** when an ingested document changes a fact, Triveni reports what it touches (stale runbooks, governing decisions the new owner must respect, memory about the service to review) and proposes an approval-gated `notify_owner` action |
| Answers with clear sources | Every tool returns `sources` (Document ids taken from `source_doc` on the edges it used), plus `cypher`, `params` and `paths` (provenance contract, `tools/base.py`) |

## Cypher and algorithms used
See [docs/queries.md](docs/queries.md). Every query is listed with its track and where it is used.

## Eval
15 questions, 5 per track, with ground truth from the seed generator. Triveni (graph tools over MCP + memory) vs a flat baseline (TF-IDF over passages of the same documents + the same model, no graph, no memory), both on `openai/gpt-oss-120b` via Groq. Full method, per-question results and notes: [docs/eval.md](docs/eval.md). Reproduce: `python -m backend.scripts.eval --out docs/eval.md`.

| Track | System | Correct | Mean F1 | Answers with evidence | Median latency | Tokens / answer |
|---|---|---|---|---|---|---|
| 01 Act | Triveni | 5/5 | 0.93 | 100% | 12.4 s | 5544 |
| 01 Act | Flat baseline | 1/5 | 0.45 | 60% | 1.7 s | 1519 |
| 02 Remember & Coordinate | Triveni | 5/5 | 0.93 | 80% | 11.0 s | 4865 |
| 02 Remember & Coordinate | Flat baseline | 0/5 | 0.00 | 60% | 1.9 s | 1161 |
| 03 Company Brain | Triveni | 5/5 | 1.00 | 100% | 6.6 s | 5535 |
| 03 Company Brain | Flat baseline | 3/5 | 0.60 | 60% | 1.3 s | 1027 |

Where the baseline does fine (C1 owner/on-call, C2 decision chain, C4 owner change, A5 the blocking ADR), the answer sits in one or two documents. Where it fails, the answer is multi-hop (blast radius, path), global (PageRank, betweenness, orphans), in memory (episodes, procedures, handoffs, conversation), or needs current-vs-stale reasoning across documents (C5).

## Data
All data is synthetic, produced by a deterministic generator (`backend/scripts/seed.py`). No private, login-gated, or personal data.

## AI usage
This project was built with AI assistance (Claude Code) for code generation and review. The team designed the graph model and can explain every query, the model, and the architecture.

At runtime, the triage agent and document extraction use free-tier models through one provider interface: Groq (`qwen/qwen3.8-27b`) first, Gemini (`gemini-3.8-flash`) as fallback, and a no-model keyword planner (`rules`) as the last resort, so the demo cannot fail on a rate limit. Every tool call goes over MCP regardless of provider. Document extractions are cached in `data/extracted/`.
