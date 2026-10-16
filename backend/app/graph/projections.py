"""Derived projection edges that the graph algorithms read (notes/graph-model.md Section 4).

FalkorDB algorithm procedures filter by label and edge type only, not by `valid_to`.
So algorithms never read State edges directly. They read these Derived edges, which
are rebuilt from *current* facts after every seed and ingest:

  (Person)-[:KNOWS {weight}]->(Service) and (Service)-[:KNOWN_BY {weight}]->(Person)
      expertise, for key_people (betweenness) and who_knows
  (Team|Person)-[:RESPONSIBLE_FOR]->(Service)
      current ownership/on-call, for find_orphans (WCC)
"""
from collections import defaultdict

from falkordb import Graph

# Evidence that a person knows a service, with its weight. Each query counts its own paths.
# The count(*) matters: when the middle node is not used after MATCH, FalkorDB's planner collapses
# the two hops into one traversal and returns each (p, s) pair once, losing repeated evidence.
EXPERTISE_EVIDENCE = [
    (3, "MATCH (p:Person)-[:RESOLVED]->(i:Incident)-[:AFFECTED]->(s:Service) RETURN p.id, s.id, count(*)"),
    (2, "MATCH (p:Person)-[:AUTHORED]->(d:Deployment)-[:DEPLOYED_TO]->(s:Service) RETURN p.id, s.id, count(*)"),
    (2, "MATCH (p:Person)-[:MADE]->(dec:Decision)-[:GOVERNS]->(s:Service) RETURN p.id, s.id, count(*)"),
    (1, "MATCH (p:Person)-[:WROTE]->(doc:Document)-[:MENTIONS]->(s:Service) RETURN p.id, s.id, count(*)"),
    (1, "MATCH (p:Person)-[r:ON_CALL_FOR]->(s:Service) WHERE r.valid_to IS NULL RETURN p.id, s.id, count(*)"),
]

CLEAR = "MATCH ()-[r:KNOWS|KNOWN_BY|RESPONSIBLE_FOR]->() DELETE r"

WRITE_KNOWS = """
UNWIND $rows AS row
MATCH (p:Person {id: row.person}), (s:Service {id: row.service})
CREATE (p)-[:KNOWS {weight: row.weight, derived: true}]->(s),
       (s)-[:KNOWN_BY {weight: row.weight, derived: true}]->(p)
"""

WRITE_RESPONSIBLE = [
    """MATCH (t:Team)-[o:OWNS]->(s:Service) WHERE o.valid_to IS NULL
       CREATE (t)-[:RESPONSIBLE_FOR {derived: true}]->(s)""",
    """MATCH (p:Person)-[o:ON_CALL_FOR]->(s:Service) WHERE o.valid_to IS NULL
       CREATE (p)-[:RESPONSIBLE_FOR {derived: true}]->(s)""",
]


def expertise_weights(graph: Graph) -> dict[tuple[str, str], int]:
    """(person id, service id) -> summed evidence weight, read from the current graph."""
    weights: dict[tuple[str, str], int] = defaultdict(int)
    for weight, query in EXPERTISE_EVIDENCE:
        for person, service, paths in graph.ro_query(query).result_set:
            weights[(person, service)] += weight * paths
    return dict(weights)


def refresh_projections(graph: Graph) -> dict[str, int]:
    """Delete and rebuild all Derived edges. Returns how many of each were written."""
    graph.query(CLEAR)
    weights = expertise_weights(graph)
    rows = [{"person": p, "service": s, "weight": w} for (p, s), w in sorted(weights.items())]
    if rows:
        graph.query(WRITE_KNOWS, {"rows": rows})
    responsible = 0
    for query in WRITE_RESPONSIBLE:
        responsible += int(graph.query(query).relationships_created)
    return {"KNOWS": len(rows), "KNOWN_BY": len(rows), "RESPONSIBLE_FOR": responsible}
