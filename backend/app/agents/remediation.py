"""Remediation agent (Track 02 coordination + Track 01 actions).

    python -m backend.app.agents.remediation --tenant acme

It is a separate agent with its own MCP server (started as agent:remediation). It learns about work only by
claiming a Handoff node from the graph (atomic), investigates with the graph tools, proposes approval-gated
actions, and marks the handoff done. It shares nothing with the triage agent except the tenant graph.
"""
import argparse
import json
import sys

import anyio
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from backend.app.agents.loop import AgentResult, print_result, run_agent, server_params

AGENT = "agent:remediation"

SYSTEM = """You are Triveni's remediation agent. You receive incidents handed over by the triage agent through the
graph. For the handoff below:
1. Use recall and similar_incidents to find what worked before, and decision_trail on the affected service to see
   which decisions constrain the fix.
2. Propose concrete next steps with propose_action: a create_ticket for the follow-up work, and notify_owner if the
   owning team must act. Propose a change (e.g. change_retry_policy) only if it is the right fix; the graph blocks it
   if a current decision forbids it, and you must then say so and suggest an allowed alternative.
3. Finish with a short summary of what you proposed and why, citing ids and sources. Do not call claim_handoff or
   complete_handoff; the system does that for you."""


async def claim(tenant: str) -> dict | None:
    """Claim the next open handoff through MCP, as agent:remediation."""
    async with stdio_client(server_params(tenant, AGENT)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("claim_handoff", {})
            data = (res.structured_content or {}).get("data") or {}
            return data if data.get("id") else None


async def complete(tenant: str, handoff_id: str, result: str) -> None:
    async with stdio_client(server_params(tenant, AGENT)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("complete_handoff", {"handoff_id": handoff_id, "result": result[:500]})


async def run_once(tenant: str, providers: list | None = None) -> tuple[dict | None, AgentResult | None]:
    handoff = await claim(tenant)
    if not handoff:
        return None, None
    p = handoff["payload"]
    question = (f"Handoff {handoff['id']} from {handoff['from']} about {handoff['incident']} "
                f"(affected: {', '.join(handoff['services']) or 'unknown'}).\nSummary: {p.get('summary')}\n"
                f"Request: {p.get('request')}")
    result = await run_agent(question, tenant, SYSTEM, providers=providers, agent=AGENT, user_id="user:remediation")
    await complete(tenant, handoff["id"], result.answer.splitlines()[0] if result.answer else "done")
    return handoff, result


def main() -> None:
    load_dotenv()
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Run the remediation agent on the next open handoff")
    ap.add_argument("--tenant", default="acme")
    args = ap.parse_args()
    handoff, result = anyio.run(run_once, args.tenant)
    if not handoff:
        print("No open handoff for agent:remediation.")
        return
    print(f"claimed {handoff['id']}: {json.dumps(handoff['payload'])}")
    print_result(result)


if __name__ == "__main__":
    main()
