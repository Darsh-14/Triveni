# Concurrency report (Track 02)

Generated 2026-10-16 11:38 UTC by `python -m backend.app.coordination.concurrency` against FalkorDB (two tenant graphs at once: conc_a, conc_b).

**16 agents in parallel, 25 operations each: 400 operations in 5.34 s (74.9 ops/s). Result: PASS.**

| Operation | n | p50 ms | p95 ms | max ms |
|---|---|---|---|---|
| claim handoff (atomic) | 67 | 32.9 | 57.6 | 59.2 |
| create handoff | 62 | 34.7 | 54.0 | 75.2 |
| append message (seq + NEXT) | 57 | 32.6 | 57.3 | 71.8 |
| recall (shared-entity traversal) | 149 | 79.9 | 113.5 | 147.2 |
| remember (Episode + INVOLVED edges) | 65 | 36.5 | 53.4 | 56.3 |

| Check | Result |
|---|---|
| Cross-tenant reads (recall/claim saw the other tenant's data) | 0 |
| Handoffs claimed twice | 0 (created 62, claimed 57) |
| Operation errors | 0 |
| `conc_a`: foreign episodes / duplicate message seq / NEXT chain | 0 / 0 / 26 edges for 27 messages |
| `conc_b`: foreign episodes / duplicate message seq / NEXT chain | 0 / 0 / 29 edges for 30 messages |

Latency is measured from this laptop to FalkorDB Cloud (ap-south-1) and includes the network round trip. Each worker opens its connection with one untimed warm-up query first.
Each tenant is its own FalkorDB graph; isolation needs no filter in the queries.
