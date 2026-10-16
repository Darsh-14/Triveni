"""propose_action (Track 01, write tool): propose an approval-gated action. Graph state decides whether it can even be
proposed: a current Decision governing the target that forbids the action kind blocks it."""
from backend.app.actions.actions import KINDS, PROPOSE, propose
from backend.app.tools.base import ToolResult, edge_ref, tool


@tool(
    name="propose_action",
    description="Propose an action for a person to approve: create_ticket, notify_owner, or a change "
                "(change_retry_policy, raise_timeout, rerun_without_reconciliation). Nothing runs until a human approves. "
                "If a current decision (ADR) governing the target forbids the action, it is recorded as blocked with "
                "the blocking decision.",
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "target": {"type": "string", "description": "service name or id, e.g. orders-api"},
            "reason": {"type": "string", "description": "why, citing evidence ids"},
            "title": {"type": "string", "description": "ticket title or message subject"},
        },
        "required": ["kind", "target", "reason"],
        "additionalProperties": False,
    },
    tracks=("01",),
    read_only=False,
    needs_agent=True,
)
def propose_action(graph, kind: str, target: str, reason: str, agent: str, title: str | None = None) -> ToolResult:
    a = propose(graph, agent, kind, target, reason, {"title": title} if title else None)
    paths = [{"nodes": [a["id"], a["target"]], "edges": [edge_ref("TARGETS", a["id"], a["target"])]}]
    paths += [{"nodes": [a["id"], d], "edges": [edge_ref("BLOCKED_BY", a["id"], d)], "stale": True} for d in a["blocked_by"]]
    explanation = (f"{kind} on {a['target']} is BLOCKED by current decision {', '.join(a['blocked_by'])}; recorded as {a['id']}."
                   if a["blocked_by"] else f"Proposed {kind} on {a['target']} as {a['id']}; waiting for human approval.")
    return ToolResult(data=a, cypher=PROPOSE.strip(), params={"kind": kind, "target": a["target"], "agent": agent},
                      paths=paths, explanation=explanation, tracks=["01", "02"])
