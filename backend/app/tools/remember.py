"""remember (Track 02, write tool): store what happened as an Episode, with an optional Lesson and Procedure.
The acting agent is set by the server, never by the model."""
from backend.app.memory.remember import CONTRADICT, EPISODE, LESSON, PROCEDURE, PROCEDURE_FOR, remember as store
from backend.app.tools.base import ToolResult, edge_ref, tool


@tool(
    name="remember",
    description="Memory: record this investigation as an episode linked to the services/incidents/people involved. "
                "Optionally add a lesson learned (reinforced if already known) and the procedure used, with "
                "procedure_result success/fail to update its counters. Call once at the end of an investigation, "
                "or when the user reports whether a fix worked.",
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "what was being investigated"},
            "outcome": {"type": "string", "enum": ["resolved", "escalated", "abandoned", "answered", "handed_off"]},
            "involved": {"type": "array", "items": {"type": "string"}, "description": "entity ids: svc:..., inc:..., per:..."},
            "lesson": {"type": "string", "description": "one sentence learned, if any"},
            "procedure_name": {"type": "string", "description": "name of the procedure used, e.g. 'Roll back payments-api'"},
            "procedure_steps": {"type": "array", "items": {"type": "string"}},
            "procedure_result": {"type": "string", "enum": ["success", "fail", "unknown"]},
        },
        "required": ["question", "outcome", "involved"],
        "additionalProperties": False,
    },
    tracks=("02",),
    read_only=False,
    needs_agent=True,
)
def remember(graph, question: str, outcome: str, involved: list[str], agent: str, lesson: str | None = None,
             procedure_name: str | None = None, procedure_steps: list[str] | None = None,
             procedure_result: str | None = None) -> ToolResult:
    procedure = {"name": procedure_name, "steps": procedure_steps or []} if procedure_name else None
    out = store(graph, agent, question, outcome, involved, lesson=lesson, procedure=procedure,
                procedure_result=procedure_result if procedure_result in ("success", "fail") else None)
    eid = out["episode"]
    paths = [{"nodes": [agent, eid], "edges": [edge_ref("RAN", agent, eid)]}]
    paths += [{"nodes": [eid, x], "edges": [edge_ref("INVOLVED", eid, x)]} for x in involved]
    if "lesson" in out:
        paths.append({"nodes": [eid, out["lesson"]["id"]], "edges": [edge_ref("LEARNED", eid, out["lesson"]["id"])]})
    if "procedure" in out:
        paths.append({"nodes": [eid, out["procedure"]["id"]], "edges": [edge_ref("USED", eid, out["procedure"]["id"])]})
    bits = [f"Stored {eid} by {agent}, linked to {out['involved']} entit(ies)"]
    if "lesson" in out:
        bits.append(f"lesson confidence {out['lesson']['confidence']}")
    if "procedure" in out:
        p = out["procedure"]
        bits.append(f"procedure {p['id']} now {p['success_count']} success / {p['fail_count']} fail")
    if out.get("weakened_lessons"):
        bits.append("weakened lessons " + ", ".join(f"{x['id']} -> {x['confidence']}" for x in out["weakened_lessons"]))
    return ToolResult(data=out, cypher="\n\n".join(q.strip() for q in (EPISODE, LESSON, PROCEDURE, PROCEDURE_FOR, CONTRADICT)),
                      params={"agent": agent, "involved": involved}, paths=paths, explanation="; ".join(bits) + ".")
