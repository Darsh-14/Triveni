"""Reset the demo tenants to a known state before a demo or a recording.

    python -m backend.scripts.demo_reset

1. Reseed acme (seed 42) and beta (seed 7): drops every episode, handoff, action and conversation.
2. Re-ingest the base documents in data/raw/*.md from the committed extraction cache (no model call).
   data/raw/live/ (the Scenario 7 billing-batch move) is left out so it can be ingested live.
3. Fill the approvals inbox with the demo actions (backend/scripts/demo_actions.py).
"""
import glob
import os

from backend.app.ingest.pipeline import ingest
from backend.scripts import demo_actions, seed


def main() -> None:
    os.environ["DEMO_REPLAY"] = "1"  # never call a model here: replay cached extractions only
    for tenant, s in (("acme", 42), ("beta", 7)):
        data = seed.generate(tenant, s)
        seed.write_ground_truth(tenant, seed.ground_truth(tenant, s, data))
        print(tenant, seed.load(tenant, data))
    for path in sorted(glob.glob("data/raw/*.md")):
        r = ingest("acme", path)
        changed = [f["fact"] for f in r["facts"] if f["action"] != "unchanged"]
        print(f"ingested {r['document']} ({r['extracted_by']}): {len(changed)} change(s)")
    demo_actions.reset("acme")  # a known approvals inbox: 5 to approve or reject, 3 blocked by current decisions
    print("ready: billing-batch is still owned by Ledger; ingest data/raw/live/chat-billing-move.md during the demo")


if __name__ == "__main__":
    main()
