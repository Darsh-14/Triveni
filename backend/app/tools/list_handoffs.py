"""list_handoffs (Track 02): handoffs between agents as stored in the graph, optionally filtered by status."""
from backend.app.coordination.handoff import LIST, list_handoffs as list_all
from backend.app.tools.base import ToolResult, edge_ref, tool


@tool(
    name="list_handoffs",
    description="Coordination: handoffs between the triage and remediation agents (open, claimed or done), with "
                "who created them, who they are for, the incident, and the summary.",
    input_schema={
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["open", "claimed", "done", "any"], "default": "open"}},
        "additionalProperties": False,
    },
    tracks=("02",),
)
def list_handoffs(graph, status: str = "open") -> ToolResult:
    items = [h for h in list_all(graph, limit=50) if status == "any" or h["status"] == status]
    paths = [{"nodes": [h["id"], h["to"]], "edges": [edge_ref("TO", h["id"], h["to"])]} for h in items]
    paths += [{"nodes": [h["id"], h["incident"]], "edges": [edge_ref("ABOUT", h["id"], h["incident"])]} for h in items if h["incident"]]
    return ToolResult(data={"status": status, "handoffs": items}, cypher=LIST.strip(), params={"limit": 50, "status": status},
                      paths=paths, explanation=f"{len(items)} handoff(s) with status {status}: "
                      + ", ".join(f"{h['id']} ({h['from']} -> {h['to']}, {h['incident']})" for h in items[:5]) if items
                      else f"No handoffs with status {status}.")
