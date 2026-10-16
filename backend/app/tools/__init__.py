"""Importing this package registers every tool in REGISTRY (one module per tool)."""
from backend.app.tools import (  # noqa: F401
    blast_radius, critical_services, decision_trail, find_orphans, ingest_document, key_people, load_history, owner_of,
    recall, remember, shortest_path, similar_incidents, who_knows, why_not,
)
from backend.app.tools.base import REGISTRY, ToolResult, run_tool  # noqa: F401
