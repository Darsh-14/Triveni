"""Triage agent (Track 01): answers on-call questions by choosing Triveni graph tools over MCP.

    python -m backend.app.agents.triage "payments-api is failing, what's affected and who do I page?" --tenant acme
"""
import argparse
import sys

import anyio
from dotenv import load_dotenv

from backend.app.agents.loop import print_result, run_agent

SYSTEM = """You are Triveni's triage agent for an engineering organisation. You answer on-call questions using the
graph tools available to you; the graph is the source of truth for services, dependencies, owners, on-call,
deployments, incidents, decisions and documents.

How to work:
- Use tools for every factual claim. If the graph has no answer, say so; why_not can prove an absence.
- Questions usually need several tools (for an outage: blast radius, the owner/on-call to page, recent deploys or
  similar incidents, governing decisions). Call independent tools in parallel.
- Before proposing a change to a service, check decision_trail with the action so a current decision is respected.
- Memory: when investigating a problem, call recall early with the services/incidents involved. If a past
  procedure worked, say so and propose reusing it. When the user reports that a fix worked or failed, call
  remember with the procedure and procedure_result so its counters stay true. Routine questions are recorded
  automatically; you don't need to call remember for them.
- Earlier turns of this conversation are included; use them for follow-up questions.

Answer format:
- Lead with the direct answer (what is affected, who to page, what to do), then the supporting facts.
- Cite evidence inline: entity ids (svc:..., per:..., inc:...) and source documents in brackets, e.g. [doc:pm-0042].
- Only state facts that a tool returned. Keep it short enough to read during an incident."""


def main() -> None:
    load_dotenv()
    sys.stdout.reconfigure(encoding="utf-8")  # answers contain arrows/emoji; Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description="Ask the Triveni triage agent")
    ap.add_argument("question")
    ap.add_argument("--tenant", default="acme")
    ap.add_argument("--conversation", help="continue a conversation stored in the graph (e.g. conv:0001)")
    args = ap.parse_args()
    result = anyio.run(lambda: run_agent(args.question, args.tenant, SYSTEM, conversation_id=args.conversation))
    print_result(result)
    print(f"conversation: {result.conversation_id}   episode: {result.episode}")


if __name__ == "__main__":
    main()
