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
