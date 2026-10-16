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
    args = ap.parse_args()
    print_result(anyio.run(run_agent, args.question, args.tenant, SYSTEM))


if __name__ == "__main__":
    main()
