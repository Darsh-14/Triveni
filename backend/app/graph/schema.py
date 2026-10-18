"""The fixed Triveni schema (MVP.md Section 3, notes/graph-model.md).

Seed and ingestion must only write labels, edge types and endpoints declared here.
`validate_node` / `validate_edge` enforce that before anything reaches FalkorDB.
"""
from dataclasses import dataclass

# --- Nodes: label -> required properties ----------------------------------
NODE_LABELS: dict[str, tuple[str, ...]] = {
    # Org
    "Person": ("id", "name", "role"),
    "Team": ("id", "name"),
    "Service": ("id", "name", "tier", "lang"),
    # Change / ops
    "Deployment": ("id", "version", "ts", "status"),
    "Incident": ("id", "title", "severity", "ts_open", "summary"),  # ts_close absent while open
    # Knowledge
    "Decision": ("id", "title", "ts", "status", "rationale", "forbids"),
    "Document": ("id", "title", "kind", "text", "ts", "source"),
    # Agents and memory
    "Agent": ("id", "name", "role"),
    "Conversation": ("id", "user_id", "started_ts"),
    "Message": ("id", "role", "text", "ts", "seq"),
    "Episode": ("id", "ts", "question", "outcome"),
    "Lesson": ("id", "text", "confidence", "last_reinforced"),
    "Procedure": ("id", "name", "steps", "success_count", "fail_count"),
    # Coordination / actions
    "Handoff": ("id", "ts", "status", "payload"),  # claimed_by set on claim
    "Action": ("id", "kind", "status", "ts", "args"),
}

DOCUMENT_KINDS = {"runbook", "postmortem", "adr", "ticket", "chat", "registry"}
ACTION_KINDS = {"create_ticket", "notify_owner", "change_retry_policy", "raise_timeout", "rerun_without_reconciliation"}
ACTION_STATUSES = {"proposed", "approved", "rejected", "blocked", "executed"}
HANDOFF_STATUSES = {"open", "claimed", "done"}

# --- Edges -----------------------------------------------------------------
STATE, EVENT, SYSTEM, DERIVED = "state", "event", "system", "derived"

# Required edge properties per category. `valid_to` is absent while a State fact is current
# (FalkorDB cannot store null), so it is never required.
CATEGORY_PROPS: dict[str, tuple[str, ...]] = {
    STATE: ("valid_from", "source_doc"),
    EVENT: ("source_doc",),
    SYSTEM: (),
    DERIVED: ("derived",),
}


@dataclass(frozen=True)
class EdgeType:
    sources: frozenset[str]
    targets: frozenset[str]
    category: str


def _e(src: str, dst: str, category: str) -> EdgeType:
    return EdgeType(frozenset(src.split("|")), frozenset(dst.split("|")), category)


EDGE_TYPES: dict[str, EdgeType] = {
    # State (temporal)
    "MEMBER_OF": _e("Person", "Team", STATE),
    "OWNS": _e("Team", "Service", STATE),
    "ON_CALL_FOR": _e("Person", "Service", STATE),
    "DEPENDS_ON": _e("Service", "Service", STATE),
    # Event (immutable facts)
    "AUTHORED": _e("Person", "Deployment", EVENT),
    "DEPLOYED_TO": _e("Deployment", "Service", EVENT),
    "AFFECTED": _e("Incident", "Service", EVENT),
    "CAUSED_BY": _e("Incident", "Deployment", EVENT),
    "RESOLVED": _e("Person", "Incident", EVENT),
    "MADE": _e("Person", "Decision", EVENT),
    "GOVERNS": _e("Decision", "Service", EVENT),
    "SUPERSEDES": _e("Decision", "Decision", EVENT),
    "EVIDENCE_FOR": _e("Document", "Incident|Decision", EVENT),
    "MENTIONS": _e("Document", "Person|Service|Team|Incident|Decision", EVENT),
    "WROTE": _e("Person", "Document", EVENT),
    # System (written by agents)
    "HAS_MESSAGE": _e("Conversation", "Message", SYSTEM),
    "NEXT": _e("Message", "Message", SYSTEM),
    "WITH": _e("Conversation", "Agent", SYSTEM),
    "RAN": _e("Agent", "Episode", SYSTEM),
    "INVOLVED": _e("Episode", "Service|Incident|Person", SYSTEM),
    "LEARNED": _e("Episode", "Lesson", SYSTEM),
    "USED": _e("Episode", "Procedure", SYSTEM),
    "FOR": _e("Procedure", "Service", SYSTEM),
    "CREATED": _e("Agent", "Handoff", SYSTEM),
    "TO": _e("Handoff", "Agent", SYSTEM),
    "ABOUT": _e("Handoff", "Incident", SYSTEM),
    "PROPOSED_IN": _e("Action", "Episode", SYSTEM),
    "TARGETS": _e("Action", "Service|Person", SYSTEM),
    "APPROVED": _e("Person", "Action", SYSTEM),
    "BLOCKED_BY": _e("Action", "Decision", SYSTEM),
    # Derived (rebuilt from current facts; algorithms read these)
    "KNOWS": _e("Person", "Service", DERIVED),
    "KNOWN_BY": _e("Service", "Person", DERIVED),
    "RESPONSIBLE_FOR": _e("Team|Person", "Service", DERIVED),
}

STATE_EDGES = frozenset(t for t, e in EDGE_TYPES.items() if e.category == STATE)
DERIVED_EDGES = frozenset(t for t, e in EDGE_TYPES.items() if e.category == DERIVED)

# Range indexes created per tenant graph (see indexes.py)
INDEXED_NODE_PROPS: dict[str, tuple[str, ...]] = {
    label: ("id", "name") if label in {"Person", "Team", "Service"} else ("id",)
    for label in NODE_LABELS
}


class SchemaError(ValueError):
    pass


def validate_node(label: str, props: dict) -> None:
    if label not in NODE_LABELS:
        raise SchemaError(f"unknown label {label!r}")
    missing = [p for p in NODE_LABELS[label] if p not in props]
    if missing:
        raise SchemaError(f"{label} {props.get('id')!r} missing {missing}")
    if any(v is None for v in props.values()):
        raise SchemaError(f"{label} {props.get('id')!r} has a null property (FalkorDB cannot store null)")
    if label == "Document" and props["kind"] not in DOCUMENT_KINDS:
        raise SchemaError(f"Document {props['id']!r} has unknown kind {props['kind']!r}")


def validate_edge(rel: str, src_label: str, dst_label: str, props: dict) -> None:
    if rel not in EDGE_TYPES:
        raise SchemaError(f"unknown edge type {rel!r}")
    et = EDGE_TYPES[rel]
    if src_label not in et.sources or dst_label not in et.targets:
        raise SchemaError(f"{rel} not allowed from {src_label} to {dst_label}")
    missing = [p for p in CATEGORY_PROPS[et.category] if p not in props]
    if missing:
        raise SchemaError(f"{rel} {src_label}->{dst_label} missing {missing}")
    if any(v is None for v in props.values()):
        raise SchemaError(f"{rel} has a null property (FalkorDB cannot store null)")
