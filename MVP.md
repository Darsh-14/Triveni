# MVP.md — Triveni

**Name:** Triveni (त्रिवेणी), "the confluence of three": three tracks, three agent capabilities (act, remember, know), one graph.

**One-liner:** An engineering Company Brain on FalkorDB where agents act on connected data, remember and coordinate through the graph, and prove every answer with a path.

**Tracks entered (all three, equal weight):**
- **Track 01 — Agents That Act on Connected Data:** Triage agent picks graph tools through MCP, reasons multi-hop, takes approval-gated actions.
- **Track 02 — Agent Memory and Coordination:** episodic/semantic/procedural memory and conversation history in the graph; agents hand off through shared graph state; per-tenant isolation; concurrent reads/writes.
- **Track 03 — Company Brain:** docs, tickets and chats ingested into one graph of people, teams, services, decisions; ownership and expertise; decision tracing; knowledge kept current; answers with sources.

Design rule: the three tracks are three pillars of one product, not three demos. Every pillar reads and writes the same tenant graph.

## 1. Problem and user

- User: on-call engineer / engineering manager.
- Pain: incident answers depend on connections (what depends on this, who owns it, what changed, which decision constrains us, who solved this before). Flat search returns pieces; agents forget past incidents; nobody can trace why an answer was given.
- Success: one question → answer, owners, evidence path, recalled prior fix, and a safe next action, in seconds.

## 2. Why the graph is load-bearing

| Capability | Graph work | Track |
|---|---|---|
| Blast radius | variable-length DEPENDS_ON traversal | 01 |
| Critical services / key people / orphans | PageRank, betweenness, connected components | 01, 03 |
| Ownership and expertise | multi-hop Person→Deployment/Incident/Decision→Service | 03 |
| Decision trace | SUPERSEDES chains + GOVERNS + EVIDENCE_FOR | 03 |
| Knowledge currency | edges carry `valid_from`/`valid_to`; queries filter on current | 03 |
| Recall | Episodes reached through shared entity neighbours, not text | 02 |
| Coordination | Handoff/Action nodes are the only channel between agents | 02 |
| Isolation | one FalkorDB graph per tenant | 02 |

Remove FalkorDB and none of these have an answer path. The eval (Section 7) shows it per track.

## 3. Graph data model (one graph per tenant: `tenant_<name>`)

Nodes
- Org: `Person {id, name, role}`, `Team {id, name}`, `Service {id, name, tier, lang}`
- Change/ops: `Deployment {id, version, ts, status}`, `Incident {id, title, severity, ts_open, ts_close, summary}`
- Knowledge: `Decision {id, title, ts, status, rationale, forbids[]}` (forbids = action kinds this decision disallows), `Document {id, title, kind, text, ts, source}` with kind ∈ {runbook, postmortem, adr, ticket, chat, registry}
- Agents: `Agent {id, name, role}`
- Memory: `Conversation {id, user_id, started_ts}`, `Message {id, role, text, ts, seq}`, `Episode {id, ts, question, outcome}`, `Lesson {id, text, confidence, last_reinforced}`, `Procedure {id, name, steps, success_count, fail_count}`
- Coordination/actions: `Handoff {id, ts, status, payload, claimed_by}`, `Action {id, kind, status, ts, args}` with status ∈ {proposed, approved, rejected, blocked, executed}
- Conventions: ids are stable and prefixed (`svc:payments-api`); time is ISO-8601 UTC strings; maps cannot be stored in FalkorDB, so `payload`/`args` are JSON strings

Edges come in four categories (details: notes/graph-model.md):
- **State** (can change): `valid_from`, `valid_to` (absent = current), `source_doc`: MEMBER_OF, OWNS, ON_CALL_FOR, DEPENDS_ON
- **Event** (immutable): `source_doc`: all other fact edges
- **System** (written by agents): memory, coordination, action edges
- **Derived** (`derived: true`, rebuilt from current facts after seed/ingest; algorithms run on these because algorithm procedures cannot filter on `valid_to`): `(Person)-[:KNOWS {weight}]->(Service)`, `(Service)-[:KNOWN_BY]->(Person)`, `(Team|Person)-[:RESPONSIBLE_FOR]->(Service)`

Edge list
- `(Person)-[:MEMBER_OF]->(Team)`, `(Team)-[:OWNS]->(Service)`, `(Person)-[:ON_CALL_FOR]->(Service)`
- `(Service)-[:DEPENDS_ON]->(Service)`
- `(Person)-[:AUTHORED]->(Deployment)-[:DEPLOYED_TO]->(Service)`
- `(Incident)-[:AFFECTED]->(Service)`, `(Incident)-[:CAUSED_BY]->(Deployment)`, `(Person)-[:RESOLVED]->(Incident)`
- `(Person)-[:MADE]->(Decision)-[:GOVERNS]->(Service)`, `(Decision)-[:SUPERSEDES]->(Decision)`
- `(Document)-[:EVIDENCE_FOR]->(Incident|Decision)`, `(Document)-[:MENTIONS]->(Person|Service|Incident|Decision)`, `(Person)-[:WROTE]->(Document)`
- `(Conversation)-[:HAS_MESSAGE]->(Message)`, `(Message)-[:NEXT]->(Message)`, `(Conversation)-[:WITH]->(Agent)`
- `(Agent)-[:RAN]->(Episode)`, `(Episode)-[:INVOLVED]->(Service|Incident|Person)`, `(Episode)-[:LEARNED]->(Lesson)`, `(Episode)-[:USED]->(Procedure)-[:FOR]->(Service)`
- `(Agent)-[:CREATED]->(Handoff)-[:TO]->(Agent)`, `(Handoff)-[:ABOUT]->(Incident)`
- `(Action)-[:PROPOSED_IN]->(Episode)`, `(Action)-[:TARGETS]->(Service|Person)`, `(Person)-[:APPROVED]->(Action)`, `(Action)-[:BLOCKED_BY]->(Decision)`

Seed: ~300 nodes / ~1.5k edges, deterministic (fixed RNG seed), planted demo needles, ground-truth answers emitted to `eval/ground_truth.json`. Tenant B: ~80 nodes, different topology.

## 4. Scope by pillar

### P0 — must ship (all three pillars, Day 1–2)

**Foundation**
1. Seed generator + loader, FalkorDB in Docker, tenant-scoped client.
2. Tool registry with provenance contract (data + cypher + params + paths + explanation).
3. Web UI: chat, graph canvas with path highlight, "Cypher used" drawer, track badge on each answer (01/02/03).

**Track 01 — Act**
4. Tools: `blast_radius`, `shortest_path`, `critical_services` (PageRank), `key_people` (betweenness), `find_orphans` (components).
5. MCP server exposing the registry; Triage agent selects tools through MCP.
6. Approval-gated actions: `create_ticket`, `notify_owner` → Action nodes + simulated outbox; approve/reject in UI.

**Track 02 — Remember and coordinate**
7. Conversation/Message persistence in the graph; reopening a conversation restores history after restart.
8. `remember` (Episode + Lesson + Procedure) and `recall` (via shared entities); Procedure success/fail counters update.
9. Two agents (Triage, Remediation) coordinating only through Handoff nodes.
10. Per-tenant graphs with an isolation test.

**Track 03 — Company Brain**
11. Ingestion pipeline: docs/tickets/chats (synthetic JSON/Markdown) → LLM extraction into the schema → MERGE into graph with `source_doc` on every edge.
12. Tools: `owner_of`, `who_knows`, `decision_trail`, `similar_incidents`, `why_not` (absence proof).
13. Every answer lists source Documents (clickable).

### P1 — strengthen each pillar (Day 3)
- **01:** multi-step plan display (which tools, in what order, why); blocked action when graph shows a governing Decision forbids it.
- **02:** concurrency demo: N parallel agents writing/reading memory, latency + zero cross-tenant leakage reported; memory decay/confidence update on Lesson.
- **03:** live update: ingest one new chat ("billing-batch moves to Team Atlas") → old OWNS edge gets `valid_to`, new edge created, same question now answers differently with both sources shown.
- Eval harness (Section 7), cached demo replay mode (`DEMO_REPLAY=1`), deploy.

### P2 — only if P0+P1 green
- Public-data overlay (an OSS repo's issues/PRs/CODEOWNERS into the same schema).
- Graphiti / GraphRAG-SDK adapter note.
- Guarded read-only free-form Cypher tool.

### Cut list
Auth/login, billing, real Slack/Jira/PagerDuty integrations, private or login-gated data, mobile layout, model training, animations, second frontend framework.

## 5. Demo scenarios (planted in seed data)

| # | Scenario | Tracks shown |
|---|---|---|
| 1 | "payments-api is failing, what's affected and who do I page?" → 3-hop dependents, owners, last deploy + author, prior incident, postmortem source | 01, 03 |
| 2 | "Can we change the retry policy on orders-api?" → SUPERSEDES chain; governing ADR superseded; stale runbook flagged; action blocked/allowed accordingly | 03, 01 |
| 3 | "Who is on call for billing-batch?" → no edge; Why-not proof; orphan list | 01, 03 |
| 4 | "Which engineers are single points of knowledge?" → betweenness ranking with paths | 01, 03 |
| 5 | Restart server, new session, similar incident → agent recalls Episode, reuses Procedure, counters update; conversation history restored | 02 |
| 6 | Triage hands off to Remediation via Handoff node; ticket proposed; human approves; Action node appears | 02, 01 |
| 7 | Ingest a chat message reassigning ownership → answer to #3 changes; old and new edges with sources | 03 |
| 8 | Tenant B: same question, isolated answer; concurrency run report | 02 |

## 6. Acceptance criteria

Foundation
- [ ] `docker compose up` + one seed command → working app; public URL works from a clean browser
- [ ] Every answer shows Cypher, path, sources, and track badge

Track 01
- [ ] Agent selects tools over MCP (visible in logs/UI)
- [ ] Scenarios 1–4 and 6 pass; at least one action is gated by graph state

Track 02
- [ ] Memory and conversation history survive restart (Scenario 5)
- [ ] Handoff is the only channel between agents (no shared in-process state)
- [ ] Isolation test passes; concurrency report generated

Track 03
- [ ] Ingestion turns raw docs/tickets/chats into graph facts with `source_doc`
- [ ] Scenario 7 shows knowledge updated, history kept
- [ ] Decision trail returns the chain to its source documents

Submission
- [ ] README has a section per track mapping its key-focus bullets to features
- [ ] 3-minute video has one chapter per track

## 7. Eval (per track)

- 15 questions with seed-generated ground truth, exact-match on entity sets:
  - 01: 5 multi-hop / algorithm questions (blast radius, path, orphans, criticality)
  - 02: 5 cross-session questions (requires recalling an earlier Episode/conversation)
  - 03: 5 ownership / decision-trace / current-vs-stale questions (asked before and after an ingest)
- Systems: Triveni graph agent vs flat baseline (TF-IDF over Document text + same LLM, no memory).
- Report per track: accuracy, answers-with-evidence %, median latency. Table in README.

## 8. Build order

seed + schema + tenant client → tool registry/provenance → ingestion (03) → agent loop over MCP (01) → API + UI path highlight → algorithms (01) → conversation + memory (02) → handoff + actions (01/02) → tenancy test (02) → live update (03) → concurrency (02) → eval → deploy → README/video/blog.

## 9. Definition of done (per feature)

Works on the demo path, has one test, its Cypher is in `docs/queries.md` tagged with the track, committed, devlog line added.
