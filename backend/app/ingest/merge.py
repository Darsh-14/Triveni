"""Merge an Extraction into a tenant graph.

1. Resolve each extracted entity to an existing node (by catalog id, then by name) or a new id.
2. Validate every node and fact against schema.py; anything invalid is rejected and reported, never written.
3. Write: the Document node (+ WROTE / MENTIONS / EVIDENCE_FOR), new entities (MERGE by id),
   Event facts (MERGE, source_doc on create), State facts through temporal.py (valid_from/valid_to).
"""
import re

from falkordb import Graph

from backend.app.graph import schema
from backend.app.ingest import temporal
from backend.app.ingest.extract import Extraction, RawDoc

PREFIX = {"Person": "per", "Team": "team", "Service": "svc", "Incident": "inc", "Decision": "adr"}
EVIDENCE_KINDS = {"postmortem", "adr", "ticket"}  # documents that are evidence for the incidents/decisions they describe


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def new_id(label: str, name: str) -> str:
    """Id for a node first seen in a document, following the seed's conventions (adr:041, inc:0081, per:ishita-rao)."""
    if label == "Decision" and (m := re.search(r"ADR-?(\d+)", name, re.I)):
        return f"adr:{int(m.group(1)):03d}"
    if label == "Incident" and (m := re.search(r"inc:?-?(\d+)", name, re.I)):
        return f"inc:{int(m.group(1)):04d}"
    return f"{PREFIX[label]}:{slug(name)}"


def _existing(graph: Graph) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    rows = graph.ro_query(
        "MATCH (n) WHERE n:Person OR n:Team OR n:Service OR n:Incident OR n:Decision "
        "RETURN n.id, labels(n)[0], toLower(coalesce(n.name, n.title))"
    ).result_set
    by_id = {node_id: label for node_id, label, _ in rows}
    by_name = {(label, name): node_id for node_id, label, name in rows}
    return by_id, by_name


def _new_node_props(entity, node_id: str, doc: RawDoc) -> dict:
    """Required properties for a node first seen in this document (defaults are explicit, not invented facts)."""
    label = entity.label
    if label == "Person":
        return {"id": node_id, "name": entity.name, "role": entity.role or "unknown"}
    if label == "Team":
        return {"id": node_id, "name": entity.name}
    if label == "Service":
        return {"id": node_id, "name": slug(entity.name), "tier": 3, "lang": "unknown"}
    if label == "Incident":
        return {"id": node_id, "title": entity.name, "severity": entity.severity or "SEV3",
                "ts_open": doc.ts, "summary": entity.summary or entity.name}
    return {"id": node_id, "title": entity.name, "ts": doc.ts, "status": "accepted",
            "rationale": entity.summary or "", "forbids": entity.forbids}


def apply(graph: Graph, doc: RawDoc, extraction: Extraction) -> dict:
    by_id, by_name = _existing(graph)
    report = {"document": doc.id, "entities": {"matched": [], "created": []}, "facts": [], "rejected": [], "cypher": []}

    # 1. resolve entities
    resolved: dict[str, tuple[str, str]] = {}  # ref -> (id, label)
    new_nodes: list[tuple[str, dict]] = []
    for e in extraction.entities:
        node_id = e.ref if by_id.get(e.ref) == e.label else by_name.get((e.label, e.name.lower()))
        if node_id is None and e.label == "Service":
            node_id = by_name.get(("Service", slug(e.name)))
        if node_id:
            report["entities"]["matched"].append(node_id)
        else:
            node_id = new_id(e.label, e.name)
            props = _new_node_props(e, node_id, doc)
            try:
                schema.validate_node(e.label, props)
            except schema.SchemaError as err:
                report["rejected"].append({"entity": e.ref, "reason": str(err)})
                continue
            if node_id not in by_id:
                new_nodes.append((e.label, props))
                by_id[node_id] = e.label
                report["entities"]["created"].append(node_id)
        resolved[e.ref] = (node_id, e.label)
        resolved.setdefault(node_id, (node_id, e.label))

    # 2. validate facts
    valid = []
    for f in extraction.facts:
        if f.src not in resolved or f.dst not in resolved:
            report["rejected"].append({"fact": f.model_dump(), "reason": "endpoint not among extracted entities"})
            continue
        (src, sl), (dst, dl) = resolved[f.src], resolved[f.dst]
        category = schema.EDGE_TYPES[f.type].category
        props = {"valid_from": doc.ts, "source_doc": doc.id} if category == schema.STATE else {"source_doc": doc.id}
        try:
            schema.validate_edge(f.type, sl, dl, props)
        except schema.SchemaError as err:
            report["rejected"].append({"fact": f.model_dump(), "reason": str(err)})
            continue
        valid.append((f, src, sl, dst, dl))

    # 3. write: document, new entities, document edges
    doc_props = {"id": doc.id, "title": doc.title, "kind": doc.kind, "text": doc.text, "ts": doc.ts, "source": doc.source}
    schema.validate_node("Document", doc_props)
    q = "MERGE (d:Document {id: $props.id}) SET d += $props"
    graph.query(q, {"props": doc_props})
    report["cypher"].append(q)
    for label, props in new_nodes:
        assert label in schema.NODE_LABELS
        graph.query(f"MERGE (n:{label} {{id: $props.id}}) SET n += $props", {"props": props})
    if new_nodes:
        report["cypher"].append("MERGE (n:<Label> {id: $props.id}) SET n += $props")

    author = by_name.get(("Person", (doc.author or "").lower()))
    if author:
        graph.query("MATCH (p:Person {id: $p}), (d:Document {id: $d}) MERGE (p)-[r:WROTE]->(d) "
                    "ON CREATE SET r.source_doc = $d", {"p": author, "d": doc.id})
    for node_id, label in {v for v in resolved.values()}:
        rel = "MENTIONS"
        schema.validate_edge(rel, "Document", label, {"source_doc": doc.id})  # same check as every other edge
        graph.query(f"MATCH (d:Document {{id: $d}}), (n:{label} {{id: $n}}) MERGE (d)-[r:{rel}]->(n) "
                    f"ON CREATE SET r.source_doc = $d", {"d": doc.id, "n": node_id})
        if doc.kind in EVIDENCE_KINDS and label in ("Incident", "Decision"):
            graph.query(f"MATCH (d:Document {{id: $d}}), (n:{label} {{id: $n}}) MERGE (d)-[r:EVIDENCE_FOR]->(n) "
                        f"ON CREATE SET r.source_doc = $d", {"d": doc.id, "n": node_id})
    report["cypher"].append("MATCH (d:Document {id: $d}), (n:<Label> {id: $n}) MERGE (d)-[r:MENTIONS]->(n) ON CREATE SET r.source_doc = $d")

    # 4. write facts
    for f, src, sl, dst, dl in valid:
        if schema.EDGE_TYPES[f.type].category == schema.STATE:
            outcome = (temporal.end_state if f.ends else temporal.assert_state)(graph, f.type, src, dst, doc.ts, doc.id)
        else:
            created = graph.query(
                f"MATCH (a:{sl} {{id: $src}}), (b:{dl} {{id: $dst}}) MERGE (a)-[r:{f.type}]->(b) "
                f"ON CREATE SET r.source_doc = $doc", {"src": src, "dst": dst, "doc": doc.id}).relationships_created
            if f.type == "SUPERSEDES":
                graph.query("MATCH (old:Decision {id: $dst}) SET old.status = 'superseded'", {"dst": dst})
            outcome = {"fact": f"{f.type}:{src}->{dst}", "action": "created" if created else "unchanged", "closed": []}
        outcome["evidence"] = f.evidence
        report["facts"].append(outcome)
    report["cypher"] += [
        "MATCH (a)-[r:<STATE>]->(b) WHERE r.valid_to IS NULL ... SET r.valid_to = $ts, r.ended_by = $doc  -- close conflicting",
        "MATCH (a), (b) CREATE (a)-[:<STATE> {valid_from: $ts, source_doc: $doc}]->(b)",
        "MATCH (a), (b) MERGE (a)-[r:<EVENT>]->(b) ON CREATE SET r.source_doc = $doc",
    ]
    return report
