"""handoff / claim_handoff / complete_handoff (Track 02): the only channel between agents is graph state."""
from backend.app.coordination.handoff import CLAIM, COMPLETE, CREATE, claim_handoff as claim, complete_handoff as complete, \
    create_handoff
from backend.app.tools.base import ToolResult, edge_ref, tool


@tool(
    name="handoff",
    description="Coordination: hand an incident over to the other agent (triage -> remediation) by writing a Handoff "
                "node into the graph with a summary of what you found and what you want done. The other agent picks "
                "it up from the graph; agents never talk directly.",
    input_schema={
        "type": "object",
        "properties": {
            "incident": {"type": "string", "description": "incident id, e.g. inc:0057"},
            "summary": {"type": "string", "description": "what you found, with ids"},
            "request": {"type": "string", "description": "what the other agent should do"},
        },
        "required": ["incident", "summary", "request"],
        "additionalProperties": False,
    },
    tracks=("02",),
    read_only=False,
    needs_agent=True,
)
def handoff(graph, incident: str, summary: str, request: str, agent: str) -> ToolResult:
    h = create_handoff(graph, agent, incident, summary, request)
    paths = [{"nodes": [agent, h["id"], h["to"]], "edges": [edge_ref("CREATED", agent, h["id"]), edge_ref("TO", h["id"], h["to"])]}]
    if h["about"]:
        paths.append({"nodes": [h["id"], h["about"]], "edges": [edge_ref("ABOUT", h["id"], h["about"])]})
    return ToolResult(data=h, cypher=CREATE.strip(), params={"from": agent, "to": h["to"], "incident": incident}, paths=paths,
                      explanation=f"Handoff {h['id']} written to the graph for {h['to']} about {h['about'] or incident} (status open).")


@tool(
    name="claim_handoff",
    description="Coordination: claim the oldest open handoff addressed to you. The claim is atomic, so two agents "
                "can never claim the same handoff. Returns nothing when there is no open handoff.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    tracks=("02",),
    read_only=False,
    needs_agent=True,
)
def claim_handoff(graph, agent: str) -> ToolResult:
    h = claim(graph, agent)
    paths = [{"nodes": [h["id"], agent], "edges": [edge_ref("TO", h["id"], agent)]}] if h else []
    return ToolResult(data=h or {"claimed": None}, cypher=CLAIM.strip(), params={"agent": agent}, paths=paths,
                      explanation=f"{agent} claimed {h['id']} from {h['from']} about {h['incident']}." if h
                      else f"No open handoff for {agent}.")


@tool(
    name="complete_handoff",
    description="Coordination: mark a handoff you claimed as done, with a one-line result.",
    input_schema={
        "type": "object",
        "properties": {"handoff_id": {"type": "string"}, "result": {"type": "string"}},
        "required": ["handoff_id", "result"],
        "additionalProperties": False,
    },
    tracks=("02",),
    read_only=False,
    needs_agent=True,
)
def complete_handoff(graph, handoff_id: str, result: str, agent: str) -> ToolResult:
    ok = complete(graph, agent, handoff_id, result)
    return ToolResult(data={"handoff_id": handoff_id, "done": ok}, cypher=COMPLETE.strip(),
                      params={"id": handoff_id, "agent": agent},
                      explanation=f"{handoff_id} marked done." if ok else f"{handoff_id} is not claimed by {agent}.")
