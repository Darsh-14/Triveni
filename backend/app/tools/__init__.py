"""Importing this package registers every tool in REGISTRY (one module per tool)."""
from backend.app.tools import ingest_document, owner_of  # noqa: F401
from backend.app.tools.base import REGISTRY, ToolResult, run_tool  # noqa: F401
