"""Reset the approvals inbox to a known set of demo actions (Track 01: approval-gated actions).

    python -m backend.scripts.demo_actions --tenant acme

1. Delete every Action node in the tenant (and its TARGETS / APPROVED / BLOCKED_BY / PROPOSED_IN edges) and clear the
   simulated outbox.
2. Propose the actions below through the normal propose() path, so the graph decides each status: an action that a
   current Decision governing the service forbids is stored as 'blocked' with a BLOCKED_BY edge; the rest wait for a
   person to approve or reject them. Every reason cites ids that exist in the seeded graph.
"""
import argparse

from backend.app.actions.actions import OUTBOX, list_actions, propose
from backend.app.graph.tenant import get_graph

DEMO_ACTIONS = [
    # (proposed by, kind, target service, reason, title)
    ("agent:triage", "create_ticket", "orders-api",
     "inc:0057: p99 latency above 4s with saturated workers; the same pattern was resolved by per:vikram-shah "
     "(postmortem doc:pm-0057). Track the worker-pool fix.", "Follow up inc:0057: orders-api worker saturation"),
    ("agent:triage", "notify_owner", "payments-api",
     "payments-api 2.14.0 was deployed on 2026-10-14; the last connection-pool change (2.12.0) caused inc:0042. "
     "Ask the on-call to watch connection errors.", "Heads-up: payments-api 2.14.0 and the inc:0042 pattern"),
    ("agent:remediation", "create_ticket", "pdf-renderer-v1",
     "pdf-renderer-v1 has no owning team and nobody on call, yet 7 services depend on it (find_orphans).",
     "Assign an owner to pdf-renderer-v1"),
    ("agent:remediation", "create_ticket", "legacy-fax-gateway",
     "legacy-fax-gateway has no owning team and nobody on call; 2 services still depend on it.",
     "Decide: decommission or adopt legacy-fax-gateway"),
    ("agent:triage", "notify_owner", "invoice-svc",
     "invoice-svc is one hop from payments-api; if payments-api degrades, invoices fail first (blast_radius).",
     "invoice-svc may be affected by payments-api"),
    # these three are forbidden by current decisions; the gate records them as blocked, nobody can approve them
    ("agent:remediation", "change_retry_policy", "orders-api",
     "Retry storms during inc:0057; propose 5 client retries with jitter.", "Raise orders-api client retries to 5"),
    ("agent:remediation", "rerun_without_reconciliation", "billing-batch",
     "The nightly billing-batch run failed; rerun it now to unblock invoicing.", "Rerun billing-batch tonight"),
    ("agent:triage", "raise_timeout", "search-api",
     "search-api queries time out under load; raise the timeout from 800 ms to 3 s.", "Raise search-api timeout to 3 s"),
]

RESET = "MATCH (a:Action) DETACH DELETE a RETURN count(a)"


def reset(tenant: str) -> list[dict]:
    graph = get_graph(tenant)
    ids = [r[0] for r in graph.ro_query("MATCH (a:Action) RETURN a.id").result_set]
    deleted = graph.query(RESET).result_set[0][0]
    removed = 0
    for aid in ids:  # only this tenant's deliveries: the outbox is shared by every tenant
        f = OUTBOX / f"{aid.replace(':', '-')}.json"
        if f.exists():
            f.unlink()
            removed += 1
    print(f"{tenant}: deleted {deleted} action(s), cleared {removed} outbox file(s)")
    for agent, kind, target, reason, title in DEMO_ACTIONS:
        a = propose(graph, agent, kind, target, reason, {"title": title})
        print(f"  {a['status']:8} {kind:30} {a['target']:24}" + (f" blocked by {', '.join(a['blocked_by'])}" if a["blocked_by"] else ""))
    return list_actions(graph)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(description="Reset the approvals inbox to the demo actions.")
    ap.add_argument("--tenant", default="acme")
    reset(ap.parse_args().tenant)


if __name__ == "__main__":
    main()
