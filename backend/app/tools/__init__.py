"""Importing this package registers every tool in REGISTRY (one module per tool)."""
from backend.app.tools import (  # noqa: F401
    blast_radius, critical_services, decision_trail, describe, find_orphans, find_services, graph_query, handoff, ingest_document, key_people, list_handoffs,
    load_history, owner_of, propose_action, recall, recent, remember, shortest_path, similar_incidents, team_services, what_if,
    who_knows, why_not,
)
from backend.app.tools.base import REGISTRY, ToolResult, run_tool  # noqa: F401
