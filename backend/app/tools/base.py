"""Tool registry and the provenance contract (CLAUDE.md "Core contracts").

Every tool returns a ToolResult: the answer (`data`) plus the evidence for it: the exact
Cypher and parameters it ran, the graph paths it found, the source Documents behind
the facts, and which track(s) it serves. The agent cites these; the UI renders them.
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from falkordb import Graph

from backend.app.graph.tenant import get_graph


@dataclass
class ToolResult:
    data: Any
    cypher: str
    params: dict
    paths: list[dict] = field(default_factory=list)  # [{"nodes": [ids], "edges": ["TYPE:src->dst"]}]
    explanation: str = ""
    tracks: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # Document ids

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


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, input_schema: dict, tracks: tuple[str, ...], read_only: bool = True):
    """Register a tool. The wrapped function takes (graph, **args) and returns a ToolResult."""
    def register(fn: Callable[..., ToolResult]):
        REGISTRY[name] = Tool(name, description, input_schema, tracks, read_only, fn)
        return fn
    return register


def run_tool(tenant: str, name: str, args: dict) -> ToolResult:
    """Run a registered tool against one tenant's graph. Tenant comes from the request, not the model."""
    if name not in REGISTRY:
        raise KeyError(f"unknown tool {name!r}")
    t = REGISTRY[name]
    result = t.fn(get_graph(tenant), **args)
    result.tracks = result.tracks or list(t.tracks)
    return result


def ro(graph: Graph, cypher: str, params: dict) -> list[list]:
    return graph.ro_query(cypher, params).result_set
