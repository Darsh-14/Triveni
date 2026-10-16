"""Concurrency run (Track 02): N agents in parallel doing remember / recall / handoff / history writes on two
tenants at once. Reports latency per operation and checks that nothing leaks across tenants and no handoff is
claimed twice.

    python -m backend.app.coordination.concurrency --agents 8 --ops 25 --out docs/concurrency.md
"""
import argparse
import random
import statistics
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from backend.app.coordination.handoff import claim_handoff, create_handoff
from backend.app.graph.tenant import get_graph
from backend.app.memory.conversation import append_message, start_conversation
from backend.app.memory.recall import recall
from backend.app.memory.remember import remember
from backend.scripts import seed

TENANTS = {"conc_a": ("acme", 42, "inc:0042", "ep:0001"), "conc_b": ("beta", 7, "inc:b001", "ep:b0001")}
AGENTS = ("agent:triage", "agent:remediation")


def pct(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def run(agents: int = 8, ops: int = 25, seed_value: int = 1) -> dict:
    for tenant, (profile, s, _, _) in TENANTS.items():
        seed.load(tenant, seed.generate(profile, s))
    conversations = {t: start_conversation(get_graph(t), "user:concurrency") for t in TENANTS}

    latencies: dict[str, list[float]] = defaultdict(list)
    leaks: list[str] = []
    claimed: list[tuple[str, str]] = []
    created: dict[str, list[str]] = defaultdict(list)
    errors: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        tenant = list(TENANTS)[i % len(TENANTS)]
        _, _, incident, _ = TENANTS[tenant]
        agent = AGENTS[(i // len(TENANTS)) % 2]  # each tenant gets both agent roles
        graph = get_graph(tenant)  # one graph handle per worker; the client pool is thread-safe
        graph.ro_query("RETURN 1")  # warm-up: opens this worker's connection outside the timed operations
        rng = random.Random(f"{seed_value}:{i}")
        for k in range(ops):
            op = rng.choice(["remember", "recall", "recall", "handoff", "claim", "message"])
            t0 = time.perf_counter()
            try:
                if op == "remember":
                    remember(graph, agent, f"[{tenant}] w{i} op{k}", "answered", ["svc:payments-api", incident])
                elif op == "recall":
                    for ep in recall(graph, ["svc:payments-api"], limit=50)["episodes"]:
                        q = ep["question"] or ""
                        if q.startswith("[") and not q.startswith(f"[{tenant}]"):
                            with lock:
                                leaks.append(f"{tenant} read {ep['id']} ({q[:30]})")
                elif op == "handoff":
                    h = create_handoff(graph, "agent:triage", incident, f"[{tenant}] w{i} op{k}", "load test")
                    with lock:
                        created[tenant].append(h["id"])
                elif op == "claim":
                    h = claim_handoff(graph, "agent:remediation")
                    if h:
                        with lock:
                            claimed.append((tenant, h["id"]))
                        if not h["payload"]["summary"].startswith(f"[{tenant}]") and h["payload"]["summary"] != "load test":
                            with lock:
                                leaks.append(f"{tenant} claimed foreign handoff {h['id']}")
                else:
                    append_message(graph, conversations[tenant], "user", f"[{tenant}] w{i} op{k}")
            except Exception as exc:  # recorded, never hidden
                with lock:
                    errors.append(f"{op}: {type(exc).__name__}: {exc}"[:200])
                continue
            with lock:
                latencies[op].append((time.perf_counter() - t0) * 1000)

    start = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(agents)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    wall = time.perf_counter() - start

    # post-run checks, read from the graph
    claimed_ids = [h for _, h in claimed]
    double_claims = len(claimed_ids) - len(set(claimed_ids))
    checks = {}
    for tenant, (_, _, _, seeded_ep) in TENANTS.items():
        g = get_graph(tenant)
        foreign = g.ro_query("MATCH (e:Episode) WHERE e.question STARTS WITH '[' AND NOT e.question STARTS WITH $p RETURN count(e)",
                             {"p": f"[{tenant}]"}).result_set[0][0]
        seqs = [r[0] for r in g.ro_query("MATCH (:Conversation {id: $c})-[:HAS_MESSAGE]->(m) RETURN m.seq",
                                         {"c": conversations[tenant]}).result_set]
        nexts = g.ro_query("MATCH (:Conversation {id: $c})-[:HAS_MESSAGE]->(a)-[:NEXT]->(b) RETURN count(*)",
                           {"c": conversations[tenant]}).result_set[0][0]
        status = dict(g.ro_query("MATCH (h:Handoff) RETURN h.status, count(h)").result_set)
        checks[tenant] = {"foreign_episodes": foreign, "messages": len(seqs), "duplicate_seq": len(seqs) - len(set(seqs)),
                          "next_edges": nexts, "handoffs": status, "seeded_episode_present": bool(
                              g.ro_query("MATCH (e:Episode {id: $e}) RETURN count(e)", {"e": seeded_ep}).result_set[0][0])}
    for tenant in TENANTS:
        get_graph(tenant).delete()
    total_ops = sum(len(v) for v in latencies.values())
    return {
        "agents": agents, "ops_per_agent": ops, "tenants": list(TENANTS), "wall_s": round(wall, 2),
        "ops": total_ops, "throughput_ops_s": round(total_ops / wall, 1),
        "latency_ms": {op: {"n": len(v), "p50": round(pct(v, 0.5), 1), "p95": round(pct(v, 0.95), 1), "max": round(max(v), 1),
                            "mean": round(statistics.mean(v), 1)} for op, v in sorted(latencies.items())},
        "cross_tenant_reads": len(leaks), "leaks": leaks[:10], "double_claims": double_claims,
        "handoffs_created": {t: len(v) for t, v in created.items()}, "handoffs_claimed": len(claimed_ids),
        "checks": checks, "errors": errors[:10], "error_count": len(errors),
    }


def to_markdown(r: dict) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ok = r["cross_tenant_reads"] == 0 and r["double_claims"] == 0 and r["error_count"] == 0 and all(
        c["foreign_episodes"] == 0 and c["duplicate_seq"] == 0 and c["next_edges"] == c["messages"] - 1 for c in r["checks"].values())
    lines = [
        "# Concurrency report (Track 02)", "",
        f"Generated {ts} by `python -m backend.app.coordination.concurrency` against FalkorDB "
        f"(two tenant graphs at once: {', '.join(r['tenants'])}).", "",
        f"**{r['agents']} agents in parallel, {r['ops_per_agent']} operations each: {r['ops']} operations in {r['wall_s']} s "
        f"({r['throughput_ops_s']} ops/s). Result: {'PASS' if ok else 'FAIL'}.**", "",
        "| Operation | n | p50 ms | p95 ms | max ms |", "|---|---|---|---|---|",
    ]
    names = {"remember": "remember (Episode + INVOLVED edges)", "recall": "recall (shared-entity traversal)",
             "handoff": "create handoff", "claim": "claim handoff (atomic)", "message": "append message (seq + NEXT)"}
    for op, s in r["latency_ms"].items():
        lines.append(f"| {names.get(op, op)} | {s['n']} | {s['p50']} | {s['p95']} | {s['max']} |")
    lines += ["", "| Check | Result |", "|---|---|",
              f"| Cross-tenant reads (recall/claim saw the other tenant's data) | {r['cross_tenant_reads']} |",
              f"| Handoffs claimed twice | {r['double_claims']} (created {sum(r['handoffs_created'].values())}, claimed {r['handoffs_claimed']}) |",
              f"| Operation errors | {r['error_count']} |"]
    for t, c in r["checks"].items():
        lines.append(f"| `{t}`: foreign episodes / duplicate message seq / NEXT chain | {c['foreign_episodes']} / {c['duplicate_seq']} / "
                     f"{c['next_edges']} edges for {c['messages']} messages |")
    lines += ["", "Latency is measured from this laptop to FalkorDB Cloud (ap-south-1) and includes the network round trip. "
              "Each worker opens its connection with one untimed warm-up query first.",
              "Each tenant is its own FalkorDB graph; isolation needs no filter in the queries."]
    if r["errors"]:
        lines += ["", "Errors:", *[f"- {e}" for e in r["errors"]]]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Triveni concurrency run (Track 02)")
    ap.add_argument("--agents", type=int, default=8)
    ap.add_argument("--ops", type=int, default=25)
    ap.add_argument("--out", default="docs/concurrency.md")
    args = ap.parse_args()
    r = run(args.agents, args.ops)
    md = to_markdown(r)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(md)


if __name__ == "__main__":
    main()
