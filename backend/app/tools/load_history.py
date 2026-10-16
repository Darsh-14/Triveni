"""load_history (Track 02): the messages of a conversation, rebuilt from the graph by walking the NEXT chain."""
from backend.app.memory.conversation import HISTORY, load_history as load
from backend.app.tools.base import ToolResult, tool


@tool(
    name="load_history",
    description="Memory: the messages of an earlier conversation, in order, rebuilt from the graph.",
    input_schema={
        "type": "object",
        "properties": {"conversation_id": {"type": "string", "description": "e.g. conv:0001"}},
        "required": ["conversation_id"],
        "additionalProperties": False,
    },
    tracks=("02",),
)
def load_history(graph, conversation_id: str) -> ToolResult:
    messages = load(graph, conversation_id)
    return ToolResult(
        data={"conversation_id": conversation_id, "messages": messages}, cypher=HISTORY.strip(),
        params={"cid": conversation_id},
        explanation=f"{len(messages)} message(s) in {conversation_id}, ordered by the NEXT chain." if messages
        else f"No messages found for {conversation_id}.")
