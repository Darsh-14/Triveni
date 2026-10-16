"""decision_trail (Track 03): decisions governing a service, their SUPERSEDES chain, sources, stale runbooks,
and (optionally) whether an action is forbidden by a current decision. Track 01 actions use the same check."""
from backend.app.actions.gate import GOVERNING, STALE, action_gate, current_decisions
from backend.app.tools.base import ToolResult, edge_ref, ro, tool

@tool(
    name="decision_trail",
    description="Decisions (ADRs) that govern a service: which is current, what each superseded, who made it, their source "
                "documents, runbooks that still cite a superseded decision (stale), and, if `action` is given "
                "(e.g. change_retry_policy), whether a current decision forbids it.",
    input_schema={
        "type": "object",
        "properties": {
            "service": {"type": "string", "description": "service name"},
            "action": {"type": "string", "description": "optional action kind to check, snake_case"},
        },
        "required": ["service"],
        "additionalProperties": False,
    },
    tracks=("03", "01"),
)
def decision_trail(graph, service: str, action: str | None = None) -> ToolResult:
    service = service.removeprefix("svc:")
    params = {"service": service}
    decisions = current_decisions(graph, service)
    by_id = {d["id"]: d for d in decisions}

    # chains: walk newer -> older starting from each current decision
    chains = []
    for d in decisions:
        if d["superseded_by"]:
            continue
        chain, cur = [d["id"]], d["id"]
        older = [x["id"] for x in decisions if cur in x["superseded_by"]]
        while older:
            cur = older[0]
            chain.append(cur)
            older = [x["id"] for x in decisions if cur in x["superseded_by"]]
        chains.append(chain)

    stale = [{"document": doc, "title": title, "ts": ts, "cites": old, "superseded_by": newer}
             for doc, title, ts, old, newer in ro(graph, STALE, params)]

    paths = []
    for d in decisions:
        paths.append({"nodes": [d["id"], d["service"]], "edges": [edge_ref("GOVERNS", d["id"], d["service"])]})
        paths += [{"nodes": [n, d["id"]], "edges": [edge_ref("SUPERSEDES", n, d["id"])]} for n in d["superseded_by"]]
        paths += [{"nodes": [src, d["id"]], "edges": [edge_ref("EVIDENCE_FOR", src, d["id"])]} for src in d["sources"]]
    paths += [{"nodes": [s["document"], s["cites"]], "edges": [edge_ref("MENTIONS", s["document"], s["cites"])], "stale": True}
              for s in stale]

    data = {"service": f"svc:{service}", "current": [c[0] for c in chains], "chains": chains,
            "decisions": decisions, "stale_runbooks": stale}
    explanation = (f"{service}: current decision(s) {', '.join(data['current']) or 'none'}; "
                   f"chain {' -> '.join(chains[0]) if chains else 'n/a'}; {len(stale)} stale runbook(s).")
    if action:
        data["gate"] = action_gate(decisions, action)
        explanation += (f" Action {action} is " + ("allowed." if data["gate"]["allowed"]
                                                   else f"blocked by {', '.join(data['gate']['blocked_by'])}."))
    sources = sorted({s for d in decisions for s in d["sources"]} | {s["document"] for s in stale})
    return ToolResult(data=data, cypher=GOVERNING.strip() + "\n\n" + STALE.strip(), params=params,
                      paths=paths, sources=sources, explanation=explanation)
