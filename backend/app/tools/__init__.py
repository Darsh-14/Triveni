"""Importing this package registers every tool in REGISTRY (one module per tool)."""
from backend.app.tools import decision_trail, ingest_document, owner_of, similar_incidents, who_knows, why_not  # noqa: F401
from backend.app.tools.base import REGISTRY, ToolResult, run_tool  # noqa: F401
