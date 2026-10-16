"""MCP server exposing Triveni's tool registry (Track 01: tool selection through MCP).

    python -m backend.app.mcp_server --tenant acme

One server process serves one tenant. The tenant is fixed at start-up and is never a tool
argument, so a model talking to this server cannot reach another tenant's graph.
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


def build_server(tenant: str) -> Server:
    graph_name(tenant)  # validates the tenant name before anything else happens

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[
            types.Tool(
                name=t.name,
                description=f"[Track {'/'.join(t.tracks)}] {t.description}",
                input_schema=t.input_schema,
                annotations=types.ToolAnnotations(read_only_hint=t.read_only, destructive_hint=False),
            )
            for t in REGISTRY.values()
        ])

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            # FalkorDB client calls are blocking; keep them off the event loop
            result = await anyio.to_thread.run_sync(lambda: run_tool(tenant, params.name, params.arguments or {}))
        except Exception as exc:  # tool errors go back to the model as is_error results, not crashes
            return types.CallToolResult(content=[types.TextContent(type="text", text=f"{type(exc).__name__}: {exc}")],
                                        is_error=True)
        payload = result.to_dict()
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload, default=str))],
                                    structured_content=payload)

    return Server("triveni", version="0.1.0",
                  instructions=f"Triveni engineering Company Brain for tenant '{tenant}'. Every result carries provenance.",
                  on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(tenant: str) -> None:
    server = build_server(tenant)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    ap = argparse.ArgumentParser(description="Triveni MCP server (stdio)")
    ap.add_argument("--tenant", default=os.getenv("TRIVENI_DEFAULT_TENANT", "acme"))
    anyio.run(serve, ap.parse_args().tenant)


if __name__ == "__main__":
    main()
