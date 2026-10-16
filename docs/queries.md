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
