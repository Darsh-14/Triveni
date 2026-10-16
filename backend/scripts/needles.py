"""Hand-written parts of the synthetic world: catalogs, named people, and the planted
needles for the 8 demo scenarios (MVP.md Section 5, notes/graph-model.md Section 5).

Everything here is fixed. seed.py fills in the random background around it.
"""

BASE_TS = "2026-01-01T00:00:00Z"

# ----------------------------------------------------------------------------- acme
ACME_TEAMS: dict[str, tuple[str, list[str]]] = {
    # team key: (display name, services owned)
    "payments": ("Payments", ["payments-api", "invoice-svc", "refund-worker", "payment-gateway-adapter", "fraud-scorer"]),
    "orders": ("Orders", ["orders-api", "cart-api", "checkout-web", "inventory-svc", "shipping-quotes"]),
    "ledger": ("Ledger", ["billing-batch", "ledger-core", "tax-calculator", "statement-renderer", "reconciliation-job"]),
    "search": ("Search", ["search-api", "indexer", "query-suggest", "ranking-svc", "catalog-sync"]),
    "platform": ("Platform", ["api-gateway", "auth-proxy", "config-svc", "feature-flags", "metrics-collector"]),
    "identity": ("Identity", ["identity-api", "sso-bridge", "session-store", "mfa-service", "user-profile"]),
    "growth": ("Growth", ["notifications-svc", "email-sender", "campaign-api", "referral-svc", "ab-testing"]),
    "atlas": ("Atlas", ["atlas-scheduler", "report-builder", "data-export"]),
}
ACME_TEAM_SIZES = {"payments": 8, "orders": 8, "ledger": 8, "search": 8, "platform": 8, "identity": 7, "growth": 7, "atlas": 6}

# Scenario 3: no owner, no on-call.
ACME_ORPHANS = ["legacy-fax-gateway", "pdf-renderer-v1"]

# Scenario 1: dependency chain into payments-api. These services never receive background
# DEPENDS_ON edges, so the blast radius and the shortest path stay exactly as planted.
ACME_PLANTED_DEPENDS = [
    ("checkout-web", "cart-api"),
    ("cart-api", "orders-api"),
    ("orders-api", "payments-api"),
    ("invoice-svc", "payments-api"),
    ("refund-worker", "invoice-svc"),
]
# Front of the topological order; background edges only point "later", so no cycles.
ACME_PROTECTED = ["checkout-web", "cart-api", "refund-worker", "orders-api", "invoice-svc", "payments-api"]

# Named people: (slug, name, team, role)
ACME_NAMED = [
    ("arjun-mehta", "Arjun Mehta", "payments", "SRE"),                 # on call for payments-api
    ("kavya-rao", "Kavya Rao", "payments", "Backend Engineer"),        # authored payments-api 2.14.0
    ("priya-nair", "Priya Nair", "payments", "Staff Engineer"),        # bridge payments <-> ledger
    ("rohan-iyer", "Rohan Iyer", "payments", "Backend Engineer"),      # authored 2.12.0 (caused inc:0042)
    ("dev-malhotra", "Dev Malhotra", "search", "Staff Engineer"),      # bridge search <-> platform
    ("meera-pillai", "Meera Pillai", "orders", "Engineering Manager"), # made adr:007
    ("vikram-shah", "Vikram Shah", "orders", "Staff Engineer"),        # made adr:019
    ("ananya-bose", "Ananya Bose", "ledger", "Engineering Manager"),   # made adr:011, adr:023
    ("farhan-qureshi", "Farhan Qureshi", "atlas", "Engineering Manager"),
]

ACME_FIRST = ["Aarav", "Aditi", "Akash", "Amrita", "Bhavna", "Chetan", "Deepa", "Divya", "Gaurav", "Harini",
              "Ishaan", "Jaya", "Karan", "Lakshmi", "Manish", "Neha", "Nikhil", "Pooja", "Rahul", "Ritu",
              "Sameer", "Sanya", "Siddharth", "Sneha", "Tanvi", "Tarun", "Uma", "Varun", "Yash", "Zoya",
              "Alex", "Maya", "Leo", "Nora", "Omar", "Sara", "Tom", "Lina", "Ivan", "Elena"]
ACME_LAST = ["Agarwal", "Banerjee", "Chopra", "Desai", "Gupta", "Joshi", "Kapoor", "Kulkarni", "Menon", "Naidu",
             "Patel", "Reddy", "Saxena", "Sinha", "Thakur", "Verma", "Wagh", "Fernandes", "Kim", "Lopez"]
ROLES = ["Backend Engineer", "Backend Engineer", "SRE", "Frontend Engineer", "Data Engineer", "Staff Engineer"]

# Scenario 2 and 7b: decision chains. (id, title, ts, maker, governs, forbids, rationale)
ACME_PLANTED_DECISIONS = [
    ("adr:007", "ADR-007: Client-side retries on orders-api", "2026-02-10T10:00:00Z", "meera-pillai", ["orders-api"], [],
     "orders-api retries failed payment calls 5 times with exponential backoff; teams may tune retry settings in the runbook."),
    ("adr:019", "ADR-019: Freeze retry policy on orders-api", "2026-07-15T09:30:00Z", "vikram-shah", ["orders-api"], ["change_retry_policy"],
     "Retry storms from orders-api amplified the payments outage. Retry policy is frozen at 2 attempts; any change needs a new ADR. Supersedes ADR-007."),
    ("adr:011", "ADR-011: Nightly billing-batch reruns allowed", "2026-02-20T11:00:00Z", "ananya-bose", ["billing-batch"], [],
     "Failed billing-batch runs may be rerun manually the same night."),
    ("adr:023", "ADR-023: billing-batch reruns need reconciliation first", "2026-08-01T08:00:00Z", "ananya-bose", ["billing-batch"], ["rerun_without_reconciliation"],
     "Manual reruns double-charged customers twice. Reconciliation-job must complete before any rerun. Supersedes ADR-011."),
]
ACME_PLANTED_SUPERSEDES = [("adr:019", "adr:007"), ("adr:023", "adr:011")]

# Scenario 1: deployments of payments-api (the only ones it gets).
ACME_PAYMENTS_DEPLOYS = [
    ("2.12.0", "2026-08-28T14:00:00Z", "rohan-iyer", "rolled_back"),
    ("2.13.0", "2026-09-20T11:00:00Z", "kavya-rao", "succeeded"),
    ("2.14.0", "2026-10-14T16:30:00Z", "kavya-rao", "succeeded"),
]

# Planted incidents: (id, title, service, severity, ts_open, ts_close or None, caused_by deploy id or None, resolvers, summary)
ACME_PLANTED_INCIDENTS = [
    ("inc:0042", "payments-api connection timeouts", "payments-api", "SEV1", "2026-09-12T08:30:00Z", "2026-09-12T10:05:00Z",
     "dep:payments-api@2.12.0", ["priya-nair"],
     "Connection pool exhausted after 2.12.0 lowered max pool size; checkout failures for 95 minutes. Fixed by rolling back to 2.11.4."),
    ("inc:0057", "orders-api p99 latency spike", "orders-api", "SEV2", "2026-10-15T07:10:00Z", None,
     None, [], "orders-api p99 latency above 4s; worker queue backing up. Under investigation."),
    ("inc:0031", "reconciliation-job stuck on month-end", "reconciliation-job", "SEV2", "2026-06-30T23:40:00Z", "2026-07-01T03:15:00Z",
     None, ["priya-nair"], "Month-end reconciliation deadlocked on payment rows; Priya from Payments patched the lock order."),
    ("inc:0063", "config-svc returning stale flags", "config-svc", "SEV3", "2026-05-18T13:00:00Z", "2026-05-18T15:20:00Z",
     None, ["dev-malhotra"], "config-svc cache TTL misread; search ranking used stale flags. Dev from Search fixed the cache key."),
]

# Planted runbooks (stale: they cite a superseded ADR).
ACME_PLANTED_RUNBOOKS = [
    ("doc:rb-orders-retry", "Runbook: tuning orders-api retries", "2026-03-05T10:00:00Z", "meera-pillai", "orders-api", "adr:007",
     "To reduce failed checkouts, raise the orders-api retry count (max 5) per ADR-007. Edit retry.max_attempts in config-svc and redeploy."),
    ("doc:rb-billing-rerun", "Runbook: rerunning billing-batch", "2026-04-12T09:00:00Z", "ananya-bose", "billing-batch", "adr:011",
     "If billing-batch fails, rerun it manually the same night per ADR-011. No other checks are needed."),
]

# Scenario 5: memory from an earlier session.
ACME_MEMORY = {
    "episode": ("ep:0001", "2026-09-12T10:10:00Z", "payments-api is timing out, what do we do?", "resolved"),
    "involved": ["inc:0042", "svc:payments-api"],
    "lesson": ("lesson:pool-exhaustion", "Lowering the payments-api pool size causes connection exhaustion under checkout load; check pool config in the last deploy first.", 0.8, "2026-09-12T10:10:00Z"),
    "procedure": ("proc:rollback-payments", "Roll back payments-api", ["Confirm the last deploy and its author", "Roll back payments-api to the previous version", "Watch pool saturation and checkout error rate for 15 min", "Page the payments on-call if errors persist"], 2, 0),
    "conversation": ("conv:0001", "user:demo", "2026-09-12T08:35:00Z"),
    "messages": [
        ("user", "payments-api is timing out, what do we do?"),
        ("assistant", "Blast radius covers orders-api, cart-api, checkout-web, invoice-svc and refund-worker. Last deploy is 2.12.0 by Rohan Iyer."),
        ("user", "Roll it back?"),
        ("assistant", "Yes: rollback recommended. Proposed procedure: Roll back payments-api. Paging Arjun Mehta (on call)."),
    ],
}

# ----------------------------------------------------------------------------- beta
BETA_TEAMS: dict[str, tuple[str, list[str]]] = {
    "core": ("Core", ["payments-api", "accounts-api", "ledger-svc", "risk-engine"]),
    "web": ("Web", ["storefront", "checkout-web", "cms-api", "image-proxy"]),
    "data": ("Data", ["etl-runner", "warehouse-loader", "reporting-api", "event-bus"]),
}
BETA_TEAM_SIZES = {"core": 7, "web": 7, "data": 6}
BETA_NAMED = [("lars-eriksen", "Lars Eriksen", "core", "SRE")]  # on call for beta payments-api
BETA_FIRST = ["Astrid", "Bjorn", "Carla", "Diego", "Emma", "Felix", "Greta", "Hugo", "Ines", "Jonas",
              "Klara", "Luca", "Marta", "Nils", "Olga", "Pablo", "Rosa", "Sven", "Tilda", "Ulla"]
BETA_LAST = ["Andersen", "Berg", "Costa", "Dahl", "Ferreira", "Hansen", "Lind", "Moreno", "Nyberg", "Rossi"]
BETA_MEMORY_EPISODE = ("ep:b0001", "2026-08-02T12:00:00Z", "beta payments-api 500s after deploy", "resolved")
