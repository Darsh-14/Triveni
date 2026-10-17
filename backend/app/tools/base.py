"""Tool registry and the provenance contract (CLAUDE.md "Core contracts").

Every tool returns a ToolResult: the answer (`data`) plus the evidence for it: the exact
Cypher and parameters it ran, the graph paths it found, the source Documents behind
the facts, and which track(s) it serves. The agent cites these; the UI renders them.

Every result also states its outcome explicitly, so an empty traversal is never mistaken for "safe":
  answered        the graph answered, with paths
  from_memory     answered from earlier episodes (Track 02)
  not_in_graph    the entity exists, but the fact asked about is not in the graph (e.g. nobody is on call)
  unknown_entity  an argument names nothing in this tenant's graph; the tool did not run (suggestions given)
  recorded        a write tool stored something (memory, handoff, action, ingest)
Entity arguments are resolved against the graph before the tool runs (graph/resolve.py).
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from falkordb import Graph

from backend.app.graph.resolve import CANDIDATES, Catalog, UnknownEntity, resolve
from backend.app.graph.tenant import get_graph

OUTCOMES = ("answered", "from_memory", "not_in_graph", "unknown_entity", "recorded")


@dataclass
class ToolResult:
    data: Any
    cypher: str
    params: dict
    paths: list[dict] = field(default_factory=list)  # [{"nodes": [ids], "edges": ["TYPE:src->dst"]}]
    explanation: str = ""
    tracks: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # Document ids
    outcome: str = ""  # one of OUTCOMES; filled in by run_tool when the tool leaves it empty
    resolved: list[dict] = field(default_factory=list)  # how each entity argument was matched to a node

    def to_dict(self) -> dict:
        return asdict(self)


def edge_ref(rel: str, src: str, dst: str) -> str:
    return f"{rel}:{src}->{dst}"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict  # JSON Schema of the arguments (tenant is added by the caller, never by the model)
    tracks: tuple[str, ...]
    read_only: bool
    fn: Callable[..., ToolResult]
    needs_agent: bool = False  # write tools that record which agent acted (set by the server, never by the model)
    # argument -> (labels or fn(args) -> labels, "id" | "name"): resolved against the graph before the tool runs
    entities: dict = field(default_factory=dict)


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, input_schema: dict, tracks: tuple[str, ...], read_only: bool = True,
         needs_agent: bool = False, entities: dict | None = None):
    """Register a tool. The wrapped function takes (graph, **args) (+ agent= if needs_agent) and returns a ToolResult.
    `entities` names the arguments that refer to graph nodes; they are resolved before the function is called."""
    def register(fn: Callable[..., ToolResult]):
        REGISTRY[name] = Tool(name, description, input_schema, tracks, read_only, fn, needs_agent, entities or {})
        return fn
    return register


def resolve_args(graph: Graph, t: Tool, args: dict) -> tuple[dict, list[dict]]:
    """Replace each entity argument by the node it names (its id or exact name). Raises UnknownEntity."""
    args, resolved, catalog = dict(args), [], None
    for arg, (labels, field_) in t.entities.items():
        if args.get(arg) in (None, "", []):
            continue
        labels = labels(args) if callable(labels) else labels
        catalog = catalog if catalog and set(labels) <= catalog_labels else None
        if catalog is None:
            catalog, catalog_labels = Catalog.load(graph, labels), set(labels)
        values = args[arg] if isinstance(args[arg], list) else [args[arg]]
        nodes = [resolve(graph, str(v), labels, catalog) for v in values]
        resolved += [n.to_dict() | {"argument": arg} for n in nodes]
        picked = [n.id if field_ == "id" else n.name for n in nodes]
        args[arg] = picked if isinstance(args[arg], list) else picked[0]
    return args, resolved


def unknown_result(t: Tool, arg: str, exc: UnknownEntity) -> ToolResult:
    return ToolResult(
        data={"found": False, "argument": arg, "query": exc.query, "labels": list(exc.labels),
              "ambiguous": exc.ambiguous, "suggestions": exc.suggestions},
        cypher=CANDIDATES, params={"labels": list(exc.labels)}, outcome="unknown_entity",
        explanation=f"{exc} Nothing else was checked: an unknown {arg} is not evidence that nothing is affected.",
        tracks=list(t.tracks))


def run_tool(tenant: str, name: str, args: dict, agent: str = "agent:triage") -> ToolResult:
    """Run a registered tool against one tenant's graph. Tenant and agent come from the caller, not the model."""
    if name not in REGISTRY:
        raise KeyError(f"unknown tool {name!r}")
    t = REGISTRY[name]
    if "agent" in args or "tenant" in args:
        raise ValueError("tenant and agent are set by the server, not passed as tool arguments")
    graph = get_graph(tenant)
    try:
        args, resolved = resolve_args(graph, t, args)
    except UnknownEntity as exc:
        arg = next((a for a in t.entities if args.get(a) not in (None, "", [])), "entity")
        for a in t.entities:  # name the argument that failed, not just the first one
            vals = args.get(a) if isinstance(args.get(a), list) else [args.get(a)]
            if exc.query in [str(v).strip() for v in vals if v is not None]:
                arg = a
                break
        return unknown_result(t, arg, exc)
    result = t.fn(graph, **args, **({"agent": agent} if t.needs_agent else {}))
    result.tracks = result.tracks or list(t.tracks)
    result.resolved = resolved
    if not result.outcome:
        result.outcome = "recorded" if not t.read_only else "answered" if result.paths else "not_in_graph"
    return result


def ro(graph: Graph, cypher: str, params: dict) -> list[list]:
    return graph.ro_query(cypher, params).result_set
