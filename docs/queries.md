# Cypher queries and algorithms

Every query Triveni runs, with the track it serves and where it lives. Values are always parameters (`$name`); only validated integers (traversal depth) are interpolated.

Tags: **[01]** Act · **[02]** Remember & Coordinate · **[03]** Company Brain · **[F]** Foundation

## Foundation

### Range indexes per tenant graph **[F]**
`backend/app/graph/indexes.py` → `ensure_indexes()`, run by the seed loader for every tenant graph.
```cypher
CREATE INDEX FOR (n:<Label>) ON (n.id)      -- every label in schema.NODE_LABELS
CREATE INDEX FOR (n:<Label>) ON (n.name)    -- Person, Team, Service
```
Issued through `Graph.create_node_range_index(label, prop)`; labels and properties come from `schema.py`, never from input. Every loader MERGE and tool lookup matches on `id` or `name`, so these keep lookups off full label scans.
