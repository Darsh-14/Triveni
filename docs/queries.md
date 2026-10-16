# Cypher queries and algorithms

Every query Triveni runs, with the track it serves and where it lives. Values are always parameters (`$name`); only validated integers (traversal depth) are interpolated.

**FalkorDB gotcha:** if a multi-hop pattern's middle node is not used after `MATCH`, the planner collapses the hops into one traversal and returns each endpoint pair once (`MATCH (p)-[:R]->(i)-[:S]->(s) RETURN p.id, s.id` gave 26 rows; `RETURN p.id, s.id, count(*)` summed to the true 34 paths). When multiplicity matters, aggregate with `count(*)` or return the middle node.

Tags: **[01]** Act · **[02]** Remember & Coordinate · **[03]** Company Brain · **[F]** Foundation

## Foundation

### Range indexes per tenant graph **[F]**
`backend/app/graph/indexes.py` → `ensure_indexes()`, run by the seed loader for every tenant graph.
```cypher
CREATE INDEX FOR (n:<Label>) ON (n.id)      -- every label in schema.NODE_LABELS
CREATE INDEX FOR (n:<Label>) ON (n.name)    -- Person, Team, Service
```
Issued through `Graph.create_node_range_index(label, prop)`; labels and properties come from `schema.py`, never from input. Every loader MERGE and tool lookup matches on `id` or `name`, so these keep lookups off full label scans.

### Seed loader **[F]**
`backend/scripts/seed.py` → `load()`. Labels/types are interpolated only after an assert that they are in `schema.py`; all values are parameters.
```cypher
UNWIND $rows AS row MERGE (n:<Label> {id: row.id}) SET n += row
UNWIND $rows AS row MATCH (a:<Src> {id: row.src}) MATCH (b:<Dst> {id: row.dst})
CREATE (a)-[r:<REL>]->(b) SET r += row.props
```

### Derived projections **[01] [03]**
`backend/app/graph/projections.py` → `refresh_projections()`, run after every seed (and, from the ingestion step, after every ingest). Algorithms read these edges because FalkorDB algorithm procedures cannot filter on `valid_to`.
```cypher
MATCH ()-[r:KNOWS|KNOWN_BY|RESPONSIBLE_FOR]->() DELETE r
-- expertise evidence (weight in brackets), summed per (person, service):
MATCH (p:Person)-[:RESOLVED]->(i:Incident)-[:AFFECTED]->(s:Service) RETURN p.id, s.id, count(*)           -- [3]
MATCH (p:Person)-[:AUTHORED]->(d:Deployment)-[:DEPLOYED_TO]->(s:Service) RETURN p.id, s.id, count(*)      -- [2]
MATCH (p:Person)-[:MADE]->(dec:Decision)-[:GOVERNS]->(s:Service) RETURN p.id, s.id, count(*)             -- [2]
MATCH (p:Person)-[:WROTE]->(doc:Document)-[:MENTIONS]->(s:Service) RETURN p.id, s.id, count(*)            -- [1]
MATCH (p:Person)-[r:ON_CALL_FOR]->(s:Service) WHERE r.valid_to IS NULL RETURN p.id, s.id, count(*)        -- [1]
UNWIND $rows AS row MATCH (p:Person {id: row.person}), (s:Service {id: row.service})
CREATE (p)-[:KNOWS {weight: row.weight, derived: true}]->(s), (s)-[:KNOWN_BY {weight: row.weight, derived: true}]->(p)
MATCH (t:Team)-[o:OWNS]->(s:Service) WHERE o.valid_to IS NULL CREATE (t)-[:RESPONSIBLE_FOR {derived: true}]->(s)
MATCH (p:Person)-[o:ON_CALL_FOR]->(s:Service) WHERE o.valid_to IS NULL CREATE (p)-[:RESPONSIBLE_FOR {derived: true}]->(s)
```

### Needle checks (tests; most become tool queries later) **[01] [02] [03]**
`backend/tests/test_needles.py`, `test_isolation.py`. Highlights:
```cypher
-- blast radius (01): who depends on $svc within 3 hops
MATCH (d:Service)-[:DEPENDS_ON*1..3]->(s:Service {id: $svc}) RETURN DISTINCT d.id
-- decision trail with sources (03)
MATCH (new:Decision)-[:SUPERSEDES]->(old:Decision)-[:GOVERNS]->(s:Service {id: $svc}) MATCH (new)-[:GOVERNS]->(s)
MATCH (src_new:Document)-[:EVIDENCE_FOR]->(new) MATCH (src_old:Document)-[:EVIDENCE_FOR]->(old)
RETURN new.id, old.id, new.forbids, src_new.id, src_old.id
-- stale runbooks (03): runbooks citing a superseded decision
MATCH (d:Document {kind: 'runbook'})-[:MENTIONS]->(old:Decision)<-[:SUPERSEDES]-(:Decision) RETURN d.id
-- orphans (01): services with no current owner/on-call
MATCH (s:Service) OPTIONAL MATCH (s)<-[r:RESPONSIBLE_FOR]-() WITH s, count(r) AS c WHERE c = 0 RETURN s.id
-- isolation (02): beta-only ids never appear in acme
MATCH (n) WHERE n.id IN $ids RETURN n.id
```

## Track 03 tools

### owner_of **[03]**
`backend/app/tools/owner_of.py`. Current facts only (`valid_to` absent); `include_history` adds superseded edges.
```cypher
MATCH (s:Service {name: $service})
OPTIONAL MATCH (t:Team)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
WITH s, collect({id: t.id, name: t.name, source: o.source_doc, since: o.valid_from}) AS owners
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(s) WHERE c.valid_to IS NULL
RETURN s.id, owners, collect({id: p.id, name: p.name, source: c.source_doc, since: c.valid_from}) AS oncall

MATCH (x)-[r:OWNS|ON_CALL_FOR]->(s:Service {name: $service})
RETURN type(r), x.id, x.name, r.valid_from, r.valid_to, r.source_doc ORDER BY r.valid_from
```

### Ingestion: merge + temporal currency **[03]**
`backend/app/ingest/merge.py`, `temporal.py`, called by `pipeline.ingest()` and the `ingest_document` tool. Labels/types are interpolated only after `schema.validate_*` accepts them.
```cypher
-- known entities shown to the extractor and used for resolution
MATCH (n) WHERE n:Person OR n:Team OR n:Service OR n:Incident OR n:Decision
RETURN labels(n)[0], n.id, coalesce(n.name, n.title)
-- the document itself, and its links
MERGE (d:Document {id: $props.id}) SET d += $props
MATCH (p:Person {id: $p}), (d:Document {id: $d}) MERGE (p)-[r:WROTE]->(d) ON CREATE SET r.source_doc = $d
MATCH (d:Document {id: $d}), (n:<Label> {id: $n}) MERGE (d)-[r:MENTIONS]->(n) ON CREATE SET r.source_doc = $d
MATCH (d:Document {id: $d}), (n:<Incident|Decision> {id: $n}) MERGE (d)-[r:EVIDENCE_FOR]->(n) ON CREATE SET r.source_doc = $d
-- Event facts: idempotent
MATCH (a:<Src> {id: $src}), (b:<Dst> {id: $dst}) MERGE (a)-[r:<EVENT>]->(b) ON CREATE SET r.source_doc = $doc
-- State facts (temporal.assert_state): 1) same fact current? 2) close conflicting current edges 3) create
MATCH (a:<Src> {id: $src})-[r:<STATE>]->(b:<Dst> {id: $dst}) WHERE r.valid_to IS NULL RETURN count(r)
MATCH (x:Team)-[r:OWNS]->(b:Service {id: $dst}) WHERE r.valid_to IS NULL AND x.id <> $src
SET r.valid_to = $ts, r.ended_by = $doc RETURN x.id                       -- OWNS / ON_CALL_FOR: one per service
MATCH (a:Person {id: $src})-[r:MEMBER_OF]->(y:Team) WHERE r.valid_to IS NULL AND y.id <> $dst
SET r.valid_to = $ts, r.ended_by = $doc RETURN y.id                       -- MEMBER_OF: one team per person
MATCH (a:<Src> {id: $src}), (b:<Dst> {id: $dst}) CREATE (a)-[:<STATE> {valid_from: $ts, source_doc: $doc}]->(b)
```
After every ingest, the Derived projections are rebuilt (see above) so expertise, responsibility and orphans reflect the new facts.

### who_knows **[03]**
`backend/app/tools/who_knows.py`. Ranks by the derived KNOWS weight, then returns every evidence path. The evidence query returns the middle node, so each path is its own row. `LIMIT` is a validated integer (1–20).
```cypher
MATCH (p:Person)-[k:KNOWS]->(s:Service {name: $service})
OPTIONAL MATCH (p)-[m:MEMBER_OF]->(t:Team) WHERE m.valid_to IS NULL
RETURN p.id, p.name, t.name, k.weight
ORDER BY k.weight DESC, p.id
LIMIT 5

MATCH (p:Person)-[r:RESOLVED]->(x:Incident)-[:AFFECTED]->(s:Service {name: $service}) WHERE p.id IN $people
RETURN p.id AS person, 'RESOLVED' AS rel, x.id AS via, x.title AS what, r.source_doc AS source, s.id AS service
UNION ALL
MATCH (p:Person)-[r:AUTHORED]->(x:Deployment)-[:DEPLOYED_TO]->(s:Service {name: $service}) WHERE p.id IN $people
RETURN p.id AS person, 'AUTHORED' AS rel, x.id AS via, x.version AS what, r.source_doc AS source, s.id AS service
UNION ALL
MATCH (p:Person)-[r:MADE]->(x:Decision)-[:GOVERNS]->(s:Service {name: $service}) WHERE p.id IN $people
RETURN p.id AS person, 'MADE' AS rel, x.id AS via, x.title AS what, r.source_doc AS source, s.id AS service
UNION ALL
MATCH (p:Person)-[:WROTE]->(x:Document)-[:MENTIONS]->(s:Service {name: $service}) WHERE p.id IN $people
RETURN p.id AS person, 'WROTE' AS rel, x.id AS via, x.title AS what, x.id AS source, s.id AS service
UNION ALL
MATCH (p:Person)-[r:ON_CALL_FOR]->(s:Service {name: $service}) WHERE p.id IN $people AND r.valid_to IS NULL
RETURN p.id AS person, 'ON_CALL_FOR' AS rel, s.id AS via, s.name AS what, r.source_doc AS source, s.id AS service
```

### decision_trail **[03] [01]**
`backend/app/tools/decision_trail.py`. A decision is current if nothing SUPERSEDES it. The chain is walked newer → older. `action_gate()` blocks an action when a current governing decision lists it in `forbids` (Scenario 2, and the gate for Track 01 actions).
```cypher
MATCH (d:Decision)-[:GOVERNS]->(s:Service {name: $service})
OPTIONAL MATCH (newer:Decision)-[:SUPERSEDES]->(d)
OPTIONAL MATCH (doc:Document)-[:EVIDENCE_FOR]->(d)
OPTIONAL MATCH (maker:Person)-[:MADE]->(d)
RETURN d.id, d.title, d.ts, d.status, d.forbids, d.rationale, s.id,
       collect(DISTINCT newer.id), collect(DISTINCT doc.id), collect(DISTINCT maker.name)
ORDER BY d.ts DESC

MATCH (doc:Document {kind: 'runbook'})-[:MENTIONS]->(old:Decision)-[:GOVERNS]->(s:Service {name: $service})
MATCH (newer:Decision)-[:SUPERSEDES]->(old)
RETURN doc.id, doc.title, doc.ts, old.id, newer.id
```

### similar_incidents **[03] [02]**
`backend/app/tools/similar_incidents.py`. Same service first (hops 0), then incidents on direct DEPENDS_ON neighbours in either direction (hops 1).
```cypher
MATCH (i:Incident {id: $incident})-[:AFFECTED]->(s:Service) RETURN s.name

MATCH (i:Incident)-[:AFFECTED]->(s:Service {name: $service})
RETURN i.id AS id, i.title AS title, i.ts_open AS ts, s.id AS via, 0 AS hops
UNION
MATCH (i:Incident)-[:AFFECTED]->(t:Service)-[d:DEPENDS_ON]-(s:Service {name: $service}) WHERE d.valid_to IS NULL
RETURN i.id AS id, i.title AS title, i.ts_open AS ts, t.id AS via, 1 AS hops

MATCH (i:Incident) WHERE i.id IN $ids
OPTIONAL MATCH (p:Person)-[:RESOLVED]->(i)
OPTIONAL MATCH (doc:Document {kind: 'postmortem'})-[:EVIDENCE_FOR]->(i)
OPTIONAL MATCH (i)-[:CAUSED_BY]->(dep:Deployment)
RETURN i.id, i.summary, i.ts_close, collect(DISTINCT p.id), collect(DISTINCT doc.id), collect(DISTINCT dep.id)
```

### why_not: absence proof **[03] [01]**
`backend/app/tools/why_not.py`. Returns the exact pattern checked, whether it matched, and the context: past edges and what ended them, the owning team, and who knows the service. Depth for `depends` is validated against {1,2,3,4} and interpolated.
```cypher
MATCH (p:Person)-[r:ON_CALL_FOR]->(s:Service {name: $service}) WHERE r.valid_to IS NULL RETURN p.id

MATCH (t:Team)-[r:OWNS]->(s:Service {name: $service}) WHERE r.valid_to IS NULL RETURN t.id

MATCH p=(a:Service {name: $from})-[:DEPENDS_ON*1..4]->(b:Service {name: $to}) RETURN [n IN nodes(p) | n.id] LIMIT 1

MATCH (x)-[r:ON_CALL_FOR]->(s:Service {name: $service}) WHERE r.valid_to IS NOT NULL
RETURN x.id, r.valid_from, r.valid_to, r.source_doc, r.ended_by

MATCH (t:Team)-[r:OWNS]->(s:Service {name: $service}) WHERE r.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[m:MEMBER_OF]->(t) WHERE m.valid_to IS NULL
OPTIONAL MATCH (p)-[k:KNOWS]->(s)
RETURN t.id, r.source_doc, p.id, p.name, coalesce(k.weight, 0) AS w ORDER BY w DESC, p.id

MATCH (p:Person)-[k:KNOWS]->(s:Service {name: $service}) RETURN p.id, p.name, k.weight ORDER BY k.weight DESC, p.id LIMIT 3
```

## Track 01 tools

### blast_radius **[01]**
`backend/app/tools/blast_radius.py`. `(A)-[:DEPENDS_ON]->(B)` means A needs B, so the blast radius of B is every service that reaches B. Only current edges count (`all(r IN relationships(p) WHERE r.valid_to IS NULL)`). Depth is validated against {1,2,3,4} and interpolated.
```cypher
MATCH p=(d:Service)-[:DEPENDS_ON*1..3]->(s:Service {name: $service})
WHERE all(r IN relationships(p) WHERE r.valid_to IS NULL)
RETURN d.id, d.name, d.tier, length(p) AS hops, [n IN nodes(p) | n.id] AS path
ORDER BY hops, d.id

MATCH (t:Team)-[o:OWNS]->(s:Service) WHERE s.id IN $ids AND o.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(s) WHERE c.valid_to IS NULL
RETURN s.id, t.id, t.name, p.id, p.name, o.source_doc, c.source_doc
```

### shortest_path **[01]**
`backend/app/tools/shortest_path.py`. `dependency` mode uses FalkorDB `shortestPath()` with the endpoints resolved first. **FalkorDB does not support undirected `shortestPath()`** (error: "does not currently support undirected shortestPath traversals"), so `any` mode is a bounded variable-length match ordered by length. The ordering must sit in a `WITH`, because `ORDER BY length(p)` after `RETURN` fails once `p` is projected away.
```cypher
MATCH (a:Service {id: $from}), (b:Service {id: $to}) WITH a, b, shortestPath((a)-[:DEPENDS_ON*1..8]->(b)) AS p WHERE p IS NOT NULL 
RETURN [n IN nodes(p) | n.id], [r IN relationships(p) | type(r)], [r IN relationships(p) | startNode(r).id], [r IN relationships(p) | r.valid_to]

MATCH p=(a {id: $from})-[:MEMBER_OF|OWNS|ON_CALL_FOR|DEPENDS_ON|AUTHORED|DEPLOYED_TO|AFFECTED|CAUSED_BY|RESOLVED|MADE|GOVERNS|SUPERSEDES*1..4]-(b {id: $to}) 
WITH p ORDER BY length(p) LIMIT 1 
RETURN [n IN nodes(p) | n.id], [r IN relationships(p) | type(r)], [r IN relationships(p) | startNode(r).id], [r IN relationships(p) | r.valid_to]
```

## Track 01: algorithms as tools

All three read only current facts. PageRank reads DEPENDS_ON, which is never ended in our data, and the tool warns if that ever changes. Betweenness and WCC read the Derived projections, which are rebuilt from current edges after every seed and ingest.

### critical_services: PageRank **[01]**
`backend/app/tools/critical_services.py`. `algo.pageRank(label, relType)` takes one label and one type. A service scores high when many services, especially critical ones, depend on it. The top 3 matches a pure-Python power iteration (damping 0.85) used as ground truth.
```cypher
CALL algo.pageRank('Service', 'DEPENDS_ON') YIELD node, score
RETURN node.id, node.name, node.tier, score
ORDER BY score DESC, node.id
LIMIT 5

MATCH (s:Service) WHERE s.id IN $ids
OPTIONAL MATCH (t:Team)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
OPTIONAL MATCH (d:Service)-[r:DEPENDS_ON]->(s) WHERE r.valid_to IS NULL
RETURN s.id, t.id, t.name, collect(DISTINCT d.id)
```

### key_people: betweenness **[01] [03]**
`backend/app/tools/key_people.py`. Runs on the expertise projection (KNOWS/KNOWN_BY). **FalkorDB samples source nodes with replacement** (measured on Cloud): with `samplingSize` = node count, scores matched no exact networkx variant and changed with the seed. From about 2,000 samples the top-2 set is stable across seeds and equals networkx's exact answer, so the tool uses `max(2000, 20 × nodes)` samples with seed 42 (0.03 s) and labels the scores as estimates.
```cypher
CALL algo.betweenness({nodeLabels: ['Person', 'Service'], relationshipTypes: ['KNOWS', 'KNOWN_BY'],
                       samplingSize: $samples, samplingSeed: $seed})
YIELD node, score
WITH node, score WHERE node:Person AND score > 0
RETURN node.id, node.name, score
ORDER BY score DESC, node.id
LIMIT 5

MATCH (p:Person)-[k:KNOWS]->(s:Service) WHERE p.id IN $ids
OPTIONAL MATCH (t:Team)-[o:OWNS]->(s) WHERE o.valid_to IS NULL
OPTIONAL MATCH (p)-[m:MEMBER_OF]->(home:Team) WHERE m.valid_to IS NULL
RETURN p.id, home.name, s.id, s.name, t.name, k.weight
```

### find_orphans: weakly connected components **[01] [03]**
`backend/app/tools/find_orphans.py`. `algo.WCC` on RESPONSIBLE_FOR (current OWNS + ON_CALL_FOR). A component holding a single Service is a service nobody is responsible for. Isolated nodes get their own component, verified on Cloud.
```cypher
CALL algo.WCC({nodeLabels: ['Team', 'Person', 'Service'], relationshipTypes: ['RESPONSIBLE_FOR']})
YIELD node, componentId
WITH componentId, collect(node) AS members
WITH componentId, members, size(members) AS n
RETURN componentId, n, [m IN members WHERE m:Service | m.id] AS services

MATCH (s:Service) WHERE s.id IN $ids
OPTIONAL MATCH (d:Service)-[r:DEPENDS_ON]->(s) WHERE r.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[k:KNOWS]->(s)
OPTIONAL MATCH (x)-[old:OWNS|ON_CALL_FOR]->(s) WHERE old.valid_to IS NOT NULL
RETURN s.id, s.name, s.tier, collect(DISTINCT d.id), collect(DISTINCT p.name), collect(DISTINCT x.id)
```

## Track 02: memory

### Conversation history **[02]**
`backend/app/memory/conversation.py`, used by the agent loop on every request and by the `load_history` tool. `seq` is computed in the same statement that creates the message. NEXT links each message to the previous one, and history is read back by walking the chain. The process keeps no state, which a test proves by reading history back in a new Python process.
```cypher
MERGE (c:Conversation {id: $id})
ON CREATE SET c.user_id = $user, c.started_ts = $ts
WITH c
MATCH (a:Agent {id: $agent})
MERGE (c)-[w:WITH]->(a) ON CREATE SET w.ts = $ts
RETURN c.id, c.started_ts

MATCH (c:Conversation {id: $cid})
OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
WITH c, max(m.seq) AS last
CREATE (c)-[:HAS_MESSAGE {ts: $ts}]->(n:Message {id: $mid, role: $role, text: $text, ts: $ts, seq: coalesce(last, -1) + 1})
WITH c, n
OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(prev:Message {seq: n.seq - 1})
FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | CREATE (prev)-[:NEXT {ts: $ts}]->(n))
RETURN n.seq

MATCH (c:Conversation {id: $cid})-[:HAS_MESSAGE]->(first:Message {seq: 0})
MATCH (first)-[:NEXT*0..500]->(m:Message)
RETURN m.role, m.text, m.seq, m.ts
ORDER BY m.seq
```

### remember: Episode, Lesson, Procedure **[02]**
`backend/app/memory/remember.py`, `tools/remember.py`. The acting agent comes from the MCP server's `--agent` flag, never from the model. A Lesson learned again is reinforced (confidence +0.1, capped at 1.0) rather than duplicated. A Procedure is reused by name and its counters updated from `procedure_result`.
```cypher
MATCH (a:Agent {id: $agent})
CREATE (a)-[:RAN {ts: $ts}]->(e:Episode {id: $eid, ts: $ts, question: $question, outcome: $outcome})
WITH e
UNWIND $involved AS xid
MATCH (x {id: xid}) WHERE x:Service OR x:Incident OR x:Person
CREATE (e)-[:INVOLVED {ts: $ts}]->(x)
RETURN count(x)

MATCH (e:Episode {id: $eid})
MERGE (l:Lesson {text: $text})
ON CREATE SET l.id = $lid, l.confidence = 0.6, l.last_reinforced = $ts
ON MATCH SET l.confidence = CASE WHEN l.confidence + 0.1 > 1.0 THEN 1.0 ELSE l.confidence + 0.1 END,
             l.last_reinforced = $ts
CREATE (e)-[:LEARNED {ts: $ts}]->(l)
RETURN l.id, l.confidence

MATCH (e:Episode {id: $eid})
MERGE (p:Procedure {name: $name})
ON CREATE SET p.id = $pid, p.steps = $steps, p.success_count = 0, p.fail_count = 0
SET p.success_count = p.success_count + $ok, p.fail_count = p.fail_count + $failed
CREATE (e)-[:USED {ts: $ts}]->(p)
RETURN p.id, p.success_count, p.fail_count

MATCH (p:Procedure {id: $pid})
UNWIND $services AS sid
MATCH (s:Service {id: sid})
MERGE (p)-[f:FOR]->(s) ON CREATE SET f.ts = $ts
RETURN count(s)
```

### recall: through shared entities, not text **[02]**
`backend/app/memory/recall.py`, `tools/recall.py`. Query entities are first expanded one hop along AFFECTED, so a brand-new incident reaches episodes about its service. Results are ranked by the number of shared entities, then by recency.
```cypher
MATCH (x) WHERE x.id IN $ids
OPTIONAL MATCH (x)-[:AFFECTED]-(y)
RETURN collect(DISTINCT x.id) + collect(DISTINCT y.id)

MATCH (e:Episode)-[:INVOLVED]->(x) WHERE x.id IN $ids
WITH e, collect(DISTINCT x.id) AS shared
OPTIONAL MATCH (e)-[:LEARNED]->(l:Lesson)
OPTIONAL MATCH (e)-[:USED]->(p:Procedure)
OPTIONAL MATCH (a:Agent)-[:RAN]->(e)
RETURN e.id, e.ts, e.question, e.outcome, shared, a.id,
       collect(DISTINCT {id: l.id, text: l.text, confidence: l.confidence}) AS lessons,
       collect(DISTINCT {id: p.id, name: p.name, steps: p.steps, success_count: p.success_count, fail_count: p.fail_count}) AS procedures
ORDER BY size(shared) DESC, e.ts DESC
LIMIT $limit
```

## Track 02: coordination, and Track 01: approval-gated actions

### Handoffs **[02]**
`backend/app/coordination/handoff.py`, tools `handoff` / `claim_handoff` / `complete_handoff`. The claim is a single statement that matches `status: 'open'` and sets `claimed`. FalkorDB runs write queries on a graph one at a time, so 8 concurrent claimers produce exactly one winner (tested). Payloads are JSON strings because maps cannot be stored as properties.
```cypher
MATCH (src:Agent {id: $from}), (dst:Agent {id: $to})
OPTIONAL MATCH (i:Incident {id: $incident})
CREATE (src)-[:CREATED {ts: $ts}]->(h:Handoff {id: $id, ts: $ts, status: 'open', payload: $payload})-[:TO {ts: $ts}]->(dst)
FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | CREATE (h)-[:ABOUT {ts: $ts}]->(i))
RETURN h.id, i.id

MATCH (h:Handoff {status: 'open'})-[:TO]->(:Agent {id: $agent})
WITH h ORDER BY h.ts LIMIT 1
SET h.status = 'claimed', h.claimed_by = $agent, h.claimed_ts = $ts
WITH h
OPTIONAL MATCH (h)-[:ABOUT]->(i:Incident)
OPTIONAL MATCH (i)-[:AFFECTED]->(s:Service)
OPTIONAL MATCH (src:Agent)-[:CREATED]->(h)
RETURN h.id, h.payload, i.id, collect(DISTINCT s.id), src.id

MATCH (h:Handoff {id: $id, status: 'claimed', claimed_by: $agent})
SET h.status = 'done', h.done_ts = $ts, h.result = $result
RETURN h.id
```

### Actions: propose, then gate, then human approval, then simulated outbox **[01] [02]**
`backend/app/actions/actions.py` + `actions/gate.py`, tool `propose_action`, API `/api/actions/{id}/decide`. The gate reuses `decision_trail`'s query: if a current Decision governing the target lists the action kind in `forbids`, the Action is stored as `blocked` with BLOCKED_BY edges and can never be approved. Status changes only from `proposed`.
```cypher
MATCH (s:Service {id: $target})
CREATE (a:Action {id: $id, kind: $kind, status: $status, ts: $ts, args: $args, proposed_by: $agent})-[:TARGETS {ts: $ts}]->(s)
WITH a
OPTIONAL MATCH (e:Episode {id: $episode})
FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END | CREATE (a)-[:PROPOSED_IN {ts: $ts}]->(e))
WITH a
UNWIND $blockers AS did
MATCH (d:Decision {id: did})
CREATE (a)-[:BLOCKED_BY {ts: $ts}]->(d)
RETURN count(d)

MATCH (a:Action {id: $id, status: 'proposed'}), (p:Person {id: $person})
SET a.status = $status, a.decided_ts = $ts
FOREACH (_ IN CASE WHEN $status = 'approved' THEN [1] ELSE [] END | CREATE (p)-[:APPROVED {ts: $ts}]->(a))
RETURN a.id, a.kind, a.args

MATCH (a:Action {id: $id, status: 'approved'}) SET a.status = 'executed', a.executed_ts = $ts, a.outbox = $file RETURN a.id
```

### team_services **[03]**
`backend/app/tools/team_services.py`. Added when the eval showed no tool could answer "which runbooks are stale for the services Team Atlas owns". Current OWNS edges only, with each service's stale runbooks.
```cypher
MATCH (t:Team)-[o:OWNS]->(s:Service) WHERE (t.id = $team OR toLower(t.name) = toLower($team)) AND o.valid_to IS NULL
OPTIONAL MATCH (p:Person)-[c:ON_CALL_FOR]->(s) WHERE c.valid_to IS NULL
RETURN t.id, t.name, s.id, s.name, o.valid_from, o.source_doc, p.id, p.name
ORDER BY s.name

MATCH (doc:Document {kind: 'runbook'})-[:MENTIONS]->(old:Decision)-[:GOVERNS]->(s:Service) WHERE s.id IN $ids
MATCH (newer:Decision)-[:SUPERSEDES]->(old)
RETURN s.id, doc.id, doc.title, old.id, newer.id
```

### list_handoffs **[02]**
`backend/app/tools/list_handoffs.py`. Added when the eval showed agents could create and claim handoffs but not list them.
```cypher
MATCH (src:Agent)-[:CREATED]->(h:Handoff)-[:TO]->(dst:Agent)
OPTIONAL MATCH (h)-[:ABOUT]->(i:Incident)
RETURN h.id, h.ts, h.status, h.payload, src.id, dst.id, i.id, h.claimed_by, h.result
ORDER BY h.ts DESC
LIMIT $limit
```

### Memory decay and contradiction **[02]**
`backend/app/memory/recall.py`, `remember.py`. Decay is applied when memory is read: effective confidence = stored confidence x 0.5^(days since last reinforced / half-life), with `TRIVENI_MEMORY_HALF_LIFE_DAYS` defaulting to 90. Lessons below 0.15 are returned but flagged `faded`, never deleted. Episodes rank by shared entities + recency. A failed procedure persistently weakens the lessons learned in episodes that used it:
```cypher
MATCH (p:Procedure {id: $pid})<-[:USED]-(e:Episode)-[:LEARNED]->(l:Lesson)
WITH DISTINCT l
SET l.confidence = CASE WHEN l.confidence - 0.15 < 0.05 THEN 0.05 ELSE l.confidence - 0.15 END
RETURN l.id, l.confidence
```

## Differentiators

### what_if: counterfactuals on a GRAPH.COPY sandbox **[01] [03]**
`backend/app/tools/what_if.py`. FalkorDB `GRAPH.COPY` clones the tenant graph in about 0.1 s on Cloud. The hypothetical change is applied **to the copy only**, the Derived projections are rebuilt there, and the same algorithms run before and after (betweenness, WCC, expertise coverage, blast radius). The result is the difference, and the copy is deleted. A test proves the real graph's node and edge counts don't change.
```cypher
GRAPH.COPY tenant_acme tenant_acme__whatif_<id>
MATCH (x:Person {id: $id}) DETACH DELETE x          -- or Team / Service, on the sandbox only
MATCH (s:Service) OPTIONAL MATCH (p:Person)-[:KNOWS]->(s) RETURN s.id, s.name, collect(p.id)
MATCH (p:Person {id: $id})
OPTIONAL MATCH (p)-[k:KNOWS]->(s:Service)
OPTIONAL MATCH (p)-[c:ON_CALL_FOR]->(oc:Service) WHERE c.valid_to IS NULL
RETURN collect(DISTINCT s.id), collect(DISTINCT oc.id)
```

### Deterministic proof check of every agent answer **[01] [02] [03]**
`backend/app/agents/verify.py`. Code, not a model, has the last word. Every id the answer cites must (1) exist in the tenant graph and (2) appear in a tool result from this run, or in the user's own question or history. Otherwise it is reported as `unknown` (an invented id) or `unbacked` (exists, but no tool showed it).
```cypher
MATCH (n) WHERE n.id IN $ids RETURN n.id
```
