# CLAUDE.md — Triveni (Graph Hacks: Context for AI Agents)

Scope authority: @MVP.md (imported automatically). When an idea conflicts with MVP.md, MVP.md wins.

## Project
Name: Triveni ("the confluence of three"). Use "Triveni" in UI, README and docs; use `triveni` for the package, repo, Docker service and env-var prefix (`TRIVENI_`).

Triveni is an engineering Company Brain on FalkorDB. Agents traverse a graph of people, teams, services, deployments, incidents, decisions, documents and past episodes to triage incidents, propose actions (with approval), remember across sessions, and prove every answer with a path.

Tracks entered: all three, equal weight. They are three pillars of one product over one tenant graph:
- **Track 01 — Act** (`backend/app/tools/`, `agents/triage.py`, `mcp_server.py`, `actions/`): multi-hop tools, algorithms as tools, MCP tool selection, graph-gated actions, explainable results.
- **Track 02 — Remember & Coordinate** (`memory/`, `agents/remediation.py`, `coordination/`): Conversation/Message history, Episode/Lesson/Procedure memory, Handoff-only coordination, per-tenant graphs, concurrency.
- **Track 03 — Company Brain** (`ingest/`, temporal edges, source tracking): docs/tickets/chats → graph, ownership/expertise, decision tracing, knowledge kept current, answers with sources.

When building any feature, state which track(s) it serves. Do not let one pillar fall behind: each day must end with a working scenario per track (MVP.md Section 5).

## Hackathon rules that constrain the code
- Event window: Oct 15 12:01 AM IST → Oct 18 11:59 PM IST. All code and commits are authored inside this window. First commit is the repo creation at kickoff.
- FalkorDB is the primary and central database. The product must stop working without it. Do not add Neo4j or another graph DB.
- Data is synthetic or public only. No private, login-gated, or personal data.
- AI-assisted code is allowed and must be disclosed in the README (section "AI usage"). The team must be able to explain every query, the graph model, and the architecture. Keep code readable; prefer simple over clever.
- Submission needs: public repo, README (setup, graph model, Cypher/algorithms used), demo video, live deploy or full local setup, track names.

## Stack
- Graph: FalkorDB (Docker locally: `docker run -p 6379:6379 -p 3000:3000 falkordb/falkordb:latest`; FalkorDB Cloud for deploy). Python client `falkordb`. Multigraph: one graph per tenant via `db.select_graph("tenant_<name>")`.
- Backend: Python 3.11+, FastAPI, Pydantic, `anthropic` SDK for the agent, `mcp` Python SDK for the MCP server.
- Model: configurable via `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`). Keys from env only.
- Frontend: Next.js + TypeScript + Tailwind; graph canvas with Cytoscape.js (or react-force-graph). One framework only.
- Eval: scikit-learn TF-IDF baseline, pytest. networkx (dev/test only) cross-checks algorithm ground truth.
- Graph model details: notes/graph-model.md (edge categories, derived projections for algorithms, needles).
- Deploy: FalkorDB Cloud + backend host (Fly.io/Render/Railway) + Vercel.

## Repo layout
```
backend/app/main.py            FastAPI app
backend/app/graph/             client, schema, tenant helpers
backend/app/tools/             tool registry (one file per tool) + provenance contract
backend/app/agents/            triage.py (01), remediation.py (02), loop.py
backend/app/actions/           approval-gated actions (01)
backend/app/memory/            conversation.py, remember.py, recall.py (02)
backend/app/coordination/      handoff.py, concurrency.py (02)
backend/app/ingest/            extract.py, merge.py, temporal.py (03)
backend/app/mcp_server.py      exposes the tool registry over MCP (01)
backend/scripts/seed.py        deterministic seed generator + loader + ground truth
backend/scripts/eval.py        per-track eval: graph agent vs flat baseline
data/raw/                      synthetic docs, tickets, chats for ingestion
backend/tests/
frontend/                      chat, graph canvas, provenance drawer, approval UI
docs/queries.md                every Cypher query/algorithm and where it is used
docs/devlog.md                 running notes (feeds the blog post)
README.md
```

## Commands (keep these working; update here if they change)
```
docker compose up -d falkordb
python -m backend.scripts.seed --tenant acme --seed 42
uvicorn backend.app.main:app --reload
pytest -q
python -m backend.scripts.eval --out docs/eval.md
npm --prefix frontend run dev
```

## Core contracts

### Tool provenance contract (every tool must return this)
```json
{
  "data": {},
  "cypher": "MATCH ...",
  "params": {},
  "paths": [{"nodes": ["Service:payments-api"], "edges": ["DEPENDS_ON:..."]}],
  "explanation": "one sentence on what the traversal shows"
}
```
The agent's final answer must cite tool results; the UI renders `paths` as a highlighted subgraph and `cypher` in a drawer.

Each tool result also carries `tracks: ["01","03"]` and `sources: [document ids]`; the UI shows track badges and clickable sources.

### Tools (P0/P1)
- Track 01: `blast_radius`, `shortest_path`, `critical_services` (PageRank), `key_people` (betweenness), `find_orphans` (components), `create_ticket` and `notify_owner` (approval-gated; refused when a current Decision GOVERNS the target and forbids it).
- Track 02: `remember`, `recall`, `load_history`, `handoff`, `claim_handoff`.
- Track 03: `owner_of`, `who_knows`, `decision_trail`, `similar_incidents`, `why_not` (absence proof), `ingest_document`.

### Cypher rules
- Always parameterize values (`$svc`, `$tenant`). Never build Cypher by string-formatting user or LLM input.
- Variable-length bounds cannot be parameters: validate depth against an allowed set (1–4) and interpolate the integer.
- Dependency direction: `(A)-[:DEPENDS_ON]->(B)` means A needs B. Blast radius of B = nodes that reach B: `MATCH p=(d:Service)-[:DEPENDS_ON*1..3]->(s:Service {name:$svc}) RETURN p`.
- Algorithm procedures: check docs.falkordb.com/algorithms for exact names and signatures before coding each one; wrap in a thin function with a test. Do not guess.
- Path multiplicity: if a multi-hop pattern's middle node is not used after MATCH, FalkorDB's planner collapses the hops and returns each endpoint pair once. When counts matter, aggregate with `count(*)` or return the middle node (verified Oct 16).
- Read tools run read-only queries. Writes happen only in `remember`, handoff and action code paths.

### Memory and coordination model (Track 02)
- Conversation history: `Conversation`-[:HAS_MESSAGE]->`Message` chained by `NEXT`; `load_history` rebuilds the LLM context from the graph on every session start.
- Episodic: `Episode` linked to entities it involved. Semantic: `Lesson` with `confidence`. Procedural: `Procedure` with `success_count`/`fail_count`.
- `recall` finds Episodes through shared entities (same Service/Incident/Person neighbors), not text search.
- Agents share state only through the graph (`Handoff` nodes with status open → claimed → done). No in-process shared state. Claim a handoff atomically in a single query (match on `status:'open'` and set to `claimed` in one statement).
- Concurrency script: N agents in parallel doing remember/recall/handoff; report p50/p95 latency and assert zero cross-tenant reads.

### Knowledge currency and sources (Track 03)
- Every extracted fact edge stores `source_doc`, `valid_from`, `valid_to` (null = current).
- New contradicting fact: set `valid_to` on the old edge, create the new one. Never delete history.
- Read tools filter `WHERE r.valid_to IS NULL` unless asked about history; answers list the source Documents.
- Ingestion: LLM extracts entities/relations into the fixed schema only (reject unknown labels/types), then MERGE by `id`/`name`.

### Multi-tenancy
- Tenant is a request-scoped parameter that selects the graph. No query may cross tenants. A test must prove isolation.

## Working agreements
- Build in the order in MVP.md Section 8. Finish the demo path (P0) before P1; P2 only if P0 and P1 are green.
- Commit small and often, conventional commits (`feat:`, `fix:`, `docs:`, `test:`). Push at least every 2 hours.
- Every feature: works on the demo path, one test, Cypher added to `docs/queries.md` tagged with its track, one devlog line.
- README keeps a section per track mapping that track's key-focus bullets to features; update it whenever a feature lands.
- If time runs short, cut P1 items evenly across tracks. Never drop a whole track.
- Tests use the seeded graph with known answers (the generator produces ground truth).
- Cached demo mode: `DEMO_REPLAY=1` replays recorded tool results so the demo survives API or network problems.
- Feature freeze: Oct 18 10:00 AM IST. After that, only fixes on the demo path, README, video, blog.
- Do not add auth, real third-party integrations, mobile layout, or anything on the MVP.md cut list.
- Secrets never committed. `.env.example` lists variables.
- When unsure about a FalkorDB behavior, test it in FalkorDB Browser (port 3000) or a scratch script before building on it.

## Definition of done for a task
Runs end-to-end on the demo path, test passes, provenance returned, queries documented, committed and pushed.
