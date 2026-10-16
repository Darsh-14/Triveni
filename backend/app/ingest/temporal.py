"""Knowledge currency for State edges (Track 03).

A State fact is asserted at a time by a source document:
  - same fact already current      -> unchanged (no duplicate edge)
  - conflicts with a current fact  -> old edge gets valid_to + ended_by, new edge created
  - otherwise                      -> new edge created
History is never deleted.

"Conflict" depends on the relation. These are functional on one side:
  OWNS        a service has one owning team      (exclusive on the target)
  ON_CALL_FOR a service has one on-call engineer (exclusive on the target)
  MEMBER_OF   a person is in one team            (exclusive on the source)
DEPENDS_ON is not exclusive: a new dependency does not end the others.
"""
from falkordb import Graph

from backend.app.graph import schema

EXCLUSIVE_SIDE = {"OWNS": "dst", "ON_CALL_FOR": "dst", "MEMBER_OF": "src"}


def _labels(rel: str) -> tuple[str, str]:
    et = schema.EDGE_TYPES[rel]
    assert et.category == schema.STATE, rel
    # State edge types have exactly one source and one target label
    (src_label,), (dst_label,) = tuple(et.sources), tuple(et.targets)
    return src_label, dst_label


def assert_state(graph: Graph, rel: str, src: str, dst: str, ts: str, doc: str) -> dict:
    """Make (src)-[rel]->(dst) the current fact as of `ts`, citing `doc`. Returns what happened."""
    sl, dl = _labels(rel)
    params = {"src": src, "dst": dst, "ts": ts, "doc": doc}
    current = graph.query(
        f"MATCH (a:{sl} {{id: $src}})-[r:{rel}]->(b:{dl} {{id: $dst}}) WHERE r.valid_to IS NULL RETURN count(r)", params
    ).result_set[0][0]
    if current:
        return {"fact": f"{rel}:{src}->{dst}", "action": "unchanged", "closed": []}

    closed = []
    side = EXCLUSIVE_SIDE.get(rel)
    if side == "dst":
        closed = [row[0] for row in graph.query(
            f"MATCH (x:{sl})-[r:{rel}]->(b:{dl} {{id: $dst}}) WHERE r.valid_to IS NULL AND x.id <> $src "
            f"SET r.valid_to = $ts, r.ended_by = $doc RETURN x.id", params).result_set]
    elif side == "src":
        closed = [row[0] for row in graph.query(
            f"MATCH (a:{sl} {{id: $src}})-[r:{rel}]->(y:{dl}) WHERE r.valid_to IS NULL AND y.id <> $dst "
            f"SET r.valid_to = $ts, r.ended_by = $doc RETURN y.id", params).result_set]

    graph.query(
        f"MATCH (a:{sl} {{id: $src}}), (b:{dl} {{id: $dst}}) "
        f"CREATE (a)-[:{rel} {{valid_from: $ts, source_doc: $doc}}]->(b)", params)
    return {"fact": f"{rel}:{src}->{dst}", "action": "created", "closed": closed}


def end_state(graph: Graph, rel: str, src: str, dst: str, ts: str, doc: str) -> dict:
    """The document says the fact stopped being true: close it without a replacement."""
    sl, dl = _labels(rel)
    n = graph.query(
        f"MATCH (a:{sl} {{id: $src}})-[r:{rel}]->(b:{dl} {{id: $dst}}) WHERE r.valid_to IS NULL "
        f"SET r.valid_to = $ts, r.ended_by = $doc RETURN count(r)",
        {"src": src, "dst": dst, "ts": ts, "doc": doc}).result_set[0][0]
    return {"fact": f"{rel}:{src}->{dst}", "action": "ended" if n else "not_current", "closed": [src] if n else []}
