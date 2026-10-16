"""Importing this package registers every tool in REGISTRY (one module per tool)."""
from backend.app.tools import (  # noqa: F401
    blast_radius, decision_trail, ingest_document, owner_of, shortest_path, similar_incidents, who_knows, why_not,
)
from backend.app.tools.base import REGISTRY, ToolResult, run_tool  # noqa: F401
