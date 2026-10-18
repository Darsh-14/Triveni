"""MCP server exposing Triveni's tool registry (Track 01: tool selection through MCP).

    python -m backend.app.mcp_server --tenant acme

One server process serves one tenant as one agent. Both are fixed at start-up and are never tool
arguments, so a model talking to this server cannot reach another tenant's graph or write as another agent.
Each tool result is returned twice: as JSON text (for any MCP client) and as structuredContent
(the full provenance contract: data, cypher, params, paths, explanation, tracks, sources).
"""
import argparse
import json
import os

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from backend.app.graph.tenant import graph_name
from backend.app.tools import REGISTRY, run_tool

# Callable over MCP but not offered to models: the remediation worker claims/completes handoffs in code, the UI
# triggers ingestion, and conversation history is injected automatically. Fewer tool definitions per turn also keeps
# prompts inside free-tier token budgets.
# team_services: covered by describe(team) and find_services(team=...); hidden to save prompt tokens on free tiers
HIDDEN_FROM_MODELS = {"claim_handoff", "complete_handoff", "ingest_document", "load_history", "team_services"}


def build_server(tenant: str, agent: str = "agent:triage") -> Server:
    graph_name(tenant)  # validates the tenant name before anything else happens

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[
            types.Tool(
                name=t.name,
                description=f"[Track {'/'.join(t.tracks)}] {t.description}",
                input_schema=t.input_schema,
                annotations=types.ToolAnnotations(read_only_hint=t.read_only, destructive_hint=False),
            )
            for t in REGISTRY.values() if t.name not in HIDDEN_FROM_MODELS
        ])

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            # FalkorDB client calls are blocking; keep them off the event loop
            result = await anyio.to_thread.run_sync(lambda: run_tool(tenant, params.name, params.arguments or {}, agent=agent))
        except Exception as exc:  # tool errors go back to the model as is_error results, not crashes
            return types.CallToolResult(content=[types.TextContent(type="text", text=f"{type(exc).__name__}: {exc}")],
                                        is_error=True)
        payload = result.to_dict()
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload, default=str))],
                                    structured_content=payload)

    return Server("triveni", version="0.1.0",
                  instructions=f"Triveni engineering Company Brain for tenant '{tenant}'. Every result carries provenance.",
                  on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(tenant: str, agent: str) -> None:
    server = build_server(tenant, agent)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    ap = argparse.ArgumentParser(description="Triveni MCP server (stdio)")
    ap.add_argument("--tenant", default=os.getenv("TRIVENI_DEFAULT_TENANT", "acme"))
    ap.add_argument("--agent", default="agent:triage", choices=["agent:triage", "agent:remediation"])
    args = ap.parse_args()
    anyio.run(serve, args.tenant, args.agent)


if __name__ == "__main__":
    main()
