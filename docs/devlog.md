# Devlog

Running notes; feeds the blog post. Newest at the bottom.

## Oct 16
- Local Docker blocked: WSL2 can't start on the dev laptop (Windows component store is missing the Virtual Machine Platform manifests; DISM repair from Windows Update and from an ISO both failed). Moved development to FalkorDB Cloud; `docker-compose.yml` stays as the reference local setup.
- Checked the `falkordb` Python client (1.8.0) API directly: `FalkorDB(host, port, username, password, ssl)`, `select_graph`, `list_graphs`, `Graph.query/ro_query(q, params)`, `create_node_range_index(label, *props)`.
- Scaffold: package, config, compose file, README skeleton with a section per track.
- Graph layer: schema.py (15 labels, 33 edge types in 4 categories, validators that reject unknown labels/types and nulls), tenant.py (`tenant_<name>`, name validated by regex), idempotent range indexes. Note: `FalkorDB()` connects eagerly (runs INFO), so construction itself fails when the server is down.
- Seed generator: deterministic (`random.Random(f"{profile}:{seed}")`), acme 296 nodes / ~1.28k edges incl. derived, beta 72 nodes. Ground truth is computed from the generated data (BFS, PageRank power iteration, orphan check), not hand-typed.
- Bug caught by networkx: scenario 4 bridges weren't the top betweenness. Background activity was random within teams, so ordinary engineers became cut points, and Dev had no Search knowledge at all. Fix: every engineer has one home service, team members are chained into a ring by on-call, and background activity only touches home services. Now {priya-nair, dev-malhotra} top betweenness on every seed tried (margin ~1.7x).
- Story change: inc:0042 is caused by payments-api 2.12.0 (Rohan, later rolled back), not the current 2.14.0 (Kavya). "Last deploy" and "prior incident cause" are now two different facts, which makes Scenario 1 more interesting.
- FalkorDB docs: `SET n.prop = NULL` removes the property (answers model-note check #1). `SET n += $map` with a parameter map is not shown in the docs; test_client checks it on load.
- FalkorDB finding (Cloud, Oct 16): `MATCH (p)-[:RESOLVED]->(i:Incident)-[:AFFECTED]->(s) RETURN p.id, s.id` returns 26 rows but there are 34 paths. EXPLAIN shows `Conditional Traverse | (s)->(p)`: when the middle node isn't used after MATCH, the planner collapses the hops and yields each endpoint pair once. Naming the node alone doesn't help; `RETURN ..., count(*)` or returning `i` does. The KNOWS projection undercounted repeated evidence; the Python mirror + projection test caught it. Rule added to CLAUDE.md.
