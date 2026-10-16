"""Deterministic seed generator + loader + ground truth.

    python -m backend.scripts.seed --tenant acme --seed 42
    python -m backend.scripts.seed --tenant beta --seed 7

`generate(profile, seed)` is pure: same profile and seed give byte-identical data.
`load(tenant, data)` replaces the tenant graph, creates indexes, loads nodes and edges,
then rebuilds the Derived projections. Ground truth goes to eval/ground_truth.json.
"""
import argparse
import json
import random
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.graph import schema
from backend.scripts import needles as N

GROUND_TRUTH_PATH = Path("eval/ground_truth.json")
PROFILES = ("acme", "beta")


# --------------------------------------------------------------------------- data container
@dataclass
class GraphData:
    nodes: dict[str, tuple[str, dict]] = field(default_factory=dict)  # id -> (label, props)
    edges: list[tuple[str, str, str, dict]] = field(default_factory=list)  # (rel, src id, dst id, props)

    def node(self, label: str, **props) -> str:
        schema.validate_node(label, props)
        if props["id"] in self.nodes:
            raise ValueError(f"duplicate node id {props['id']}")
        self.nodes[props["id"]] = (label, props)
        return props["id"]

    def edge(self, rel: str, src: str, dst: str, **props) -> None:
        schema.validate_edge(rel, self.label(src), self.label(dst), props)
        self.edges.append((rel, src, dst, props))

    def label(self, node_id: str) -> str:
        return self.nodes[node_id][0]

    def ids(self, label: str) -> list[str]:
        return [i for i, (lbl, _) in self.nodes.items() if lbl == label]

    def out(self, rel: str, src: str, current_only: bool = True) -> list[str]:
        return [d for r, s, d, p in self.edges
                if r == rel and s == src and not (current_only and "valid_to" in p)]


# --------------------------------------------------------------------------- helpers
def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def rand_ts(rng: random.Random, start: str = "2026-01-05T00:00:00Z", end: str = "2026-10-10T00:00:00Z") -> str:
    a = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    b = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return iso(a + timedelta(seconds=rng.randrange(int((b - a).total_seconds()))))


def slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def make_people(rng, data, teams, sizes, named, first, last) -> dict[str, list[str]]:
    """Create Person nodes + MEMBER_OF edges. Returns team key -> member person ids."""
    members: dict[str, list[str]] = {t: [] for t in teams}
    used = set()
    for s, name, team, role in named:
        data.node("Person", id=f"per:{s}", name=name, role=role)
        members[team].append(f"per:{s}")
        used.add(s)
    pool = [f"{f} {l}" for f in first for l in last]
    rng.shuffle(pool)
    for team in teams:
        while len(members[team]) < sizes[team]:
            name = pool.pop()
            if slug(name) in used:
                continue
            used.add(slug(name))
            data.node("Person", id=f"per:{slug(name)}", name=name, role=rng.choice(N.ROLES))
            members[team].append(f"per:{slug(name)}")
    for team, people in members.items():
        for p in people:
            data.edge("MEMBER_OF", p, f"team:{team}", valid_from=N.BASE_TS, source_doc="doc:org-chart")
    return members


def registry_docs(data, teams, members, oncall) -> None:
    """Service catalog, org chart, on-call schedule and deploy log: the cited source of baseline facts.
    Their text states every fact they are cited for (owners, dependencies, members, on-call, deployments)."""
    owner_of = {svc: name for _, (name, svcs) in teams.items() for svc in svcs}
    deps = defaultdict(list)
    for rel, src, dst, _ in data.edges:
        if rel == "DEPENDS_ON":
            deps[src].append(dst[4:])
    catalog = "\n".join(
        f"{sid[4:]}: " + (f"owned by Team {owner_of[sid[4:]]}" if sid[4:] in owner_of else "no owning team")
        + (f"; depends on {', '.join(sorted(deps[sid]))}" if deps[sid] else "; no dependencies")
        for sid in sorted(data.ids("Service")))
    if "doc:deploy-log" in data.nodes:
        authored = {dst: src for rel, src, dst, _ in data.edges if rel == "AUTHORED"}
        lines = []
        for dep_id in sorted(data.ids("Deployment"), key=lambda d: data.nodes[d][1]["ts"]):
            props = data.nodes[dep_id][1]
            svc, author = dep_id[4:].split("@")[0], data.nodes[authored[dep_id]][1]["name"]
            lines.append(f"{props['ts']} {svc} {props['version']} deployed by {author} ({props['status']})")
        data.nodes["doc:deploy-log"][1]["text"] = "Deployment history exported from CI.\n" + "\n".join(lines)
    org = "\n".join(f"{data.nodes[p][1]['name']}: Team {teams[t][0]}" for t, ps in members.items() for p in ps)
    sched = "\n".join(f"{s[4:]}: {data.nodes[p][1]['name']}" for s, p in oncall.items())
    data.node("Document", id="doc:service-catalog", title="Service catalog", kind="registry", text=catalog, ts=N.BASE_TS, source="seed")
    data.node("Document", id="doc:org-chart", title="Org chart", kind="registry", text=org, ts=N.BASE_TS, source="seed")
    data.node("Document", id="doc:oncall-schedule", title="On-call schedule", kind="registry", text=sched, ts=N.BASE_TS, source="seed")
    for svc in data.ids("Service"):
        data.edge("MENTIONS", "doc:service-catalog", svc, source_doc="doc:service-catalog")
    for ps in members.values():
        for p in ps:
            data.edge("MENTIONS", "doc:org-chart", p, source_doc="doc:org-chart")
    for s, p in oncall.items():
        data.edge("MENTIONS", "doc:oncall-schedule", s, source_doc="doc:oncall-schedule")
        data.edge("MENTIONS", "doc:oncall-schedule", p, source_doc="doc:oncall-schedule")


def doc(data, doc_id, title, kind, text, ts, author=None, mentions=(), evidence_for=()) -> None:
    data.node("Document", id=doc_id, title=title, kind=kind, text=text, ts=ts, source="seed")
    if author:
        data.edge("WROTE", author, doc_id, source_doc=doc_id)
    for m in mentions:
        data.edge("MENTIONS", doc_id, m, source_doc=doc_id)
    for e in evidence_for:
        data.edge("EVIDENCE_FOR", doc_id, e, source_doc=doc_id)


def caused_by_decisions(data: "GraphData", services: list[str]) -> list[str]:
    """Current decisions governing these services (cited by postmortems as the rules in force)."""
    superseded = {d for r, _, d, _ in data.edges if r == "SUPERSEDES"}
    return sorted({s for r, s, d, _ in data.edges if r == "GOVERNS" and d in services and s not in superseded})


def background_depends(rng, data, services, protected, planted, per_service=(1, 3)) -> None:
    """DAG of DEPENDS_ON: protected services first, then a shuffled order; edges point later only."""
    for a, b in planted:
        data.edge("DEPENDS_ON", f"svc:{a}", f"svc:{b}", valid_from=N.BASE_TS, source_doc="doc:service-catalog")
    rest = [s for s in services if s not in protected]
    rng.shuffle(rest)
    order = protected + rest
    for i, a in enumerate(order):
        later = [b for b in order[i + 1:] if b not in protected]
        for b in rng.sample(later, min(len(later), rng.randint(*per_service))):
            data.edge("DEPENDS_ON", f"svc:{a}", f"svc:{b}", valid_from=N.BASE_TS, source_doc="doc:service-catalog")


def deploy(data, svc, version, ts, author, status) -> str:
    dep_id = f"dep:{svc}@{version}"
    data.node("Deployment", id=dep_id, version=version, ts=ts, status=status)
    data.edge("AUTHORED", f"per:{author}" if not author.startswith("per:") else author, dep_id, source_doc="doc:deploy-log")
    data.edge("DEPLOYED_TO", dep_id, f"svc:{svc}", source_doc="doc:deploy-log")
    return dep_id


def incident(data, inc_id, title, svc, severity, ts_open, ts_close, caused_by, resolvers, summary) -> None:
    props = dict(id=inc_id, title=title, severity=severity, ts_open=ts_open, summary=summary)
    if ts_close:
        props["ts_close"] = ts_close
    data.node("Incident", **props)
    # Closed incidents are sourced from their postmortem, open ones from their ticket.
    source = f"doc:pm-{inc_id[4:]}" if ts_close else f"doc:tkt-{inc_id[4:]}"
    data.edge("AFFECTED", inc_id, f"svc:{svc}", source_doc=source)
    if caused_by:
        data.edge("CAUSED_BY", inc_id, caused_by, source_doc=source)
    for r in resolvers:
        data.edge("RESOLVED", r if r.startswith("per:") else f"per:{r}", inc_id, source_doc=source)


# --------------------------------------------------------------------------- acme
def generate_acme(rng: random.Random) -> GraphData:
    data = GraphData()
    teams = N.ACME_TEAMS
    owner = {svc: t for t, (_, svcs) in teams.items() for svc in svcs}

    for t, (name, _) in teams.items():
        data.node("Team", id=f"team:{t}", name=name)
    langs = ["python", "go", "java", "typescript", "kotlin"]
    for svc in list(owner) + N.ACME_ORPHANS:
        data.node("Service", id=f"svc:{svc}", name=svc, tier=1 if svc in N.ACME_PROTECTED else rng.choice([1, 2, 2, 3]),
                  lang=rng.choice(langs))

    members = make_people(rng, data, teams, N.ACME_TEAM_SIZES, N.ACME_NAMED, N.ACME_FIRST, N.ACME_LAST)
    bridges = {"per:priya-nair", "per:dev-malhotra"}

    # Knowledge structure (scenario 4). Every engineer has one home service they deploy to.
    # Within a team, member i is also on call for the service after their home service, which
    # links the team into a ring: no ordinary engineer is the only path between two services.
    # Background activity (incidents, decisions, docs) only touches a person's home service,
    # so the planted bridges (priya-nair, dev-malhotra) are the only people spanning two teams.
    home: dict[str, str] = {}
    oncall: dict[str, str] = {"svc:payments-api": "per:arjun-mehta"}
    for t, (_, svcs) in teams.items():
        ring = [s for s in svcs if s != "payments-api"]  # payments-api keeps its planted deploy history
        people = sorted(members[t])
        rng.shuffle(people)
        if "billing-batch" in ring:
            # billing-batch has no on-call (scenario 3); Ananya's decisions govern it, so she closes the ring there.
            people.remove("per:ananya-bose")
            people.insert((ring.index("billing-batch") - 1) % len(ring), "per:ananya-bose")
        for j, p in enumerate(people):
            home[p] = ring[j % len(ring)]
        for i, svc in enumerate(ring):
            if svc != "billing-batch":
                oncall[f"svc:{svc}"] = people[(i - 1) % len(ring)]

    def knower(svc: str) -> str:
        """Someone who already knows `svc` (home service), never a bridge."""
        if svc == "payments-api":
            return rng.choice(["per:kavya-rao", "per:rohan-iyer", "per:arjun-mehta"])
        return rng.choice(sorted(p for p, h in home.items() if h == svc and p not in bridges))

    # State: ownership and on-call
    for svc, t in owner.items():
        valid_from = "2026-03-01T00:00:00Z" if svc == "billing-batch" else N.BASE_TS
        data.edge("OWNS", f"team:{t}", f"svc:{svc}", valid_from=valid_from, source_doc="doc:service-catalog")
    for s, p in oncall.items():
        data.edge("ON_CALL_FOR", p, s, valid_from=N.BASE_TS, source_doc="doc:oncall-schedule")

    background_depends(rng, data, list(owner) + N.ACME_ORPHANS, N.ACME_PROTECTED, N.ACME_PLANTED_DEPENDS, per_service=(2, 5))

    # Deployments: payments-api gets only the planted three; everyone else deploys their home service once.
    data.node("Document", id="doc:deploy-log", title="Deploy log", kind="registry",
              text="Deployment history exported from CI.", ts=N.BASE_TS, source="seed")
    for version, ts, author, status in N.ACME_PAYMENTS_DEPLOYS:
        deploy(data, "payments-api", version, ts, author, status)
    deploys_of = defaultdict(list)
    for person, svc in sorted(home.items()):
        version = f"{rng.randint(1, 4)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}"
        while f"dep:{svc}@{version}" in data.nodes:
            version = f"{rng.randint(1, 4)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}"
        ts = rand_ts(rng)
        dep_id = deploy(data, svc, version, ts, person, rng.choice(["succeeded"] * 5 + ["failed", "rolled_back"]))
        deploys_of[svc].append((ts, dep_id))
    for svc in deploys_of:
        deploys_of[svc].sort()

    # Decisions: planted chains + background (never governing orders-api or billing-batch)
    for dec_id, title, ts, maker, governs, forbids, rationale in N.ACME_PLANTED_DECISIONS:
        superseded = any(old == dec_id for _, old in N.ACME_PLANTED_SUPERSEDES)
        data.node("Decision", id=dec_id, title=title, ts=ts, status="superseded" if superseded else "accepted",
                  rationale=rationale, forbids=forbids)
        data.edge("MADE", f"per:{maker}", dec_id, source_doc=f"doc:{dec_id.replace(':', '-')}")
        for g in governs:
            data.edge("GOVERNS", dec_id, f"svc:{g}", source_doc=f"doc:{dec_id.replace(':', '-')}")
    for new, old in N.ACME_PLANTED_SUPERSEDES:
        data.edge("SUPERSEDES", new, old, source_doc=f"doc:{new.replace(':', '-')}")
    adr_numbers = [n for n in range(1, 40) if f"adr:{n:03d}" not in data.nodes]
    bg_decisions = []
    for n in sorted(rng.sample(adr_numbers, 13)):
        t = rng.choice([t for t in teams if t != "atlas"])
        candidates = [s for s in teams[t][1] if s not in ("orders-api", "billing-batch", "payments-api")]
        governs = [rng.choice(candidates)]
        dec_id = f"adr:{n:03d}"
        ts = rand_ts(rng)
        maker = knower(governs[0])
        data.node("Decision", id=dec_id, title=f"ADR-{n:03d}: {governs[0]} {rng.choice(['timeouts', 'caching', 'schema change', 'rate limits', 'storage'])}",
                  ts=ts, status="accepted", rationale=f"Standardise {governs[0]} behaviour after review.", forbids=[])
        data.edge("MADE", maker, dec_id, source_doc=f"doc:adr-{n:03d}")
        for g in governs:
            data.edge("GOVERNS", dec_id, f"svc:{g}", source_doc=f"doc:adr-{n:03d}")
        bg_decisions.append((ts, dec_id, t, maker, governs))
    by_team = defaultdict(list)
    for item in sorted(bg_decisions):
        by_team[item[2]].append(item)
    pairs = [(lst[-1][1], lst[0][1]) for lst in by_team.values() if len(lst) >= 2]
    for new, old in pairs[:3]:
        data.edge("SUPERSEDES", new, old, source_doc=f"doc:{new.replace(':', '-')}")
        label, props = data.nodes[old]
        props["status"] = "superseded"

    # Incidents: planted + 26 background, each inside its owning team
    for inc in N.ACME_PLANTED_INCIDENTS:
        incident(data, *inc)
    planted_numbers = {int(i[0][4:]) for i in N.ACME_PLANTED_INCIDENTS}
    numbers = sorted(rng.sample([n for n in range(1, 80) if n not in planted_numbers], 26))
    bg_services = [s for s in owner if s not in ("payments-api", "orders-api")]
    for n in numbers:
        svc = rng.choice(bg_services)
        t = owner[svc]
        ts_open = rand_ts(rng)
        ts_close = iso(datetime.strptime(ts_open, "%Y-%m-%dT%H:%M:%SZ") + timedelta(minutes=rng.randint(20, 400)))
        earlier = [d for ts, d in deploys_of[svc] if ts < ts_open]
        caused = earlier[-1] if earlier and rng.random() < 0.7 else None
        resolvers = sorted({knower(svc) for _ in range(rng.choice([1, 1, 2]))})
        incident(data, f"inc:{n:04d}", f"{svc} {rng.choice(['error spike', 'latency regression', 'outage', 'data delay', 'memory leak'])}",
                 svc, rng.choice(["SEV2", "SEV3", "SEV3"]), ts_open, ts_close, caused, resolvers,
                 f"{svc} degraded; resolved by the {teams[t][0]} team.")

    # Documents
    registry_docs(data, teams, members, oncall)
    for dec_id, (label, props) in [(i, data.nodes[i]) for i in data.ids("Decision")]:
        makers = [s for r, s, d, _ in data.edges if r == "MADE" and d == dec_id]
        governed = [d for r, s, d, _ in data.edges if r == "GOVERNS" and s == dec_id]
        doc(data, f"doc:{dec_id.replace(':', '-')}", props["title"], "adr", props["rationale"], props["ts"],
            author=makers[0], mentions=governed + makers + [dec_id], evidence_for=[dec_id])
    for inc_id in data.ids("Incident"):
        props = data.nodes[inc_id][1]
        if "ts_close" not in props:
            continue
        resolvers = [s for r, s, d, _ in data.edges if r == "RESOLVED" and d == inc_id]
        svc = [d for r, s, d, _ in data.edges if r == "AFFECTED" and s == inc_id]
        caused = [d for r, s, d, _ in data.edges if r == "CAUSED_BY" and s == inc_id]
        deployer = [s for r, s, d, _ in data.edges if r == "AUTHORED" and caused and d == caused[0]]
        text = props["summary"] + (f" Root cause: deployment {caused[0][4:]}." if caused else "")
        doc(data, f"doc:pm-{inc_id[4:]}", f"Postmortem: {props['title']}", "postmortem", text, props["ts_close"],
            author=resolvers[0], mentions=svc + sorted(set(resolvers + deployer)) + [inc_id] + caused_by_decisions(data, svc),
            evidence_for=[inc_id])
    for doc_id, title, ts, author, svc, adr, text in N.ACME_PLANTED_RUNBOOKS:
        doc(data, doc_id, title, "runbook", text, ts, author=f"per:{author}", mentions=[f"svc:{svc}", adr])
    for i, svc in enumerate(rng.sample([s for s in owner if s not in ("orders-api", "billing-batch")], 8)):
        doc(data, f"doc:rb-{svc}", f"Runbook: {svc}", "runbook", f"How to restart and scale {svc}.", rand_ts(rng),
            author=knower(svc), mentions=[f"svc:{svc}"])
    open_or_recent = ["inc:0057"] + [i for i in data.ids("Incident") if i != "inc:0057"][:4]
    for inc_id in open_or_recent:
        svc = [d for r, s, d, _ in data.edges if r == "AFFECTED" and s == inc_id][0]
        doc(data, f"doc:tkt-{inc_id[4:]}", f"Ticket: {data.nodes[inc_id][1]['title']}", "ticket",
            f"Tracking ticket for {inc_id}. Service: {svc[4:]}.", data.nodes[inc_id][1]["ts_open"],
            author=knower(svc[4:]), mentions=[svc, inc_id], evidence_for=[inc_id])
    for i, t in enumerate(["search", "platform", "growth"]):
        svc = rng.choice(teams[t][1])
        doc(data, f"doc:chat-{i + 1:04d}", f"Chat: #{t}-eng", "chat", f"Heads up: {svc} deploy window moved to Thursday.",
            rand_ts(rng), author=knower(svc), mentions=[f"svc:{svc}"])

    add_agents_and_memory_acme(data)
    return data


def add_agents_and_memory_acme(data: GraphData) -> None:
    data.node("Agent", id="agent:triage", name="Triage", role="triage")
    data.node("Agent", id="agent:remediation", name="Remediation", role="remediation")
    m = N.ACME_MEMORY
    ep_id, ts, question, outcome = m["episode"]
    data.node("Episode", id=ep_id, ts=ts, question=question, outcome=outcome)
    data.edge("RAN", "agent:triage", ep_id, ts=ts)
    for target in m["involved"]:
        data.edge("INVOLVED", ep_id, target, ts=ts)
    lesson_id, text, confidence, reinforced = m["lesson"]
    data.node("Lesson", id=lesson_id, text=text, confidence=confidence, last_reinforced=reinforced)
    data.edge("LEARNED", ep_id, lesson_id, ts=ts)
    proc_id, name, steps, ok, fail = m["procedure"]
    data.node("Procedure", id=proc_id, name=name, steps=steps, success_count=ok, fail_count=fail)
    data.edge("USED", ep_id, proc_id, ts=ts)
    data.edge("FOR", proc_id, "svc:payments-api", ts=ts)
    conv_id, user_id, started = m["conversation"]
    data.node("Conversation", id=conv_id, user_id=user_id, started_ts=started)
    data.edge("WITH", conv_id, "agent:triage", ts=started)
    prev = None
    for seq, (role, text) in enumerate(m["messages"]):
        msg_id = f"msg:0001-{seq:02d}"
        msg_ts = iso(datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ") + timedelta(minutes=seq))
        data.node("Message", id=msg_id, role=role, text=text, ts=msg_ts, seq=seq)
        data.edge("HAS_MESSAGE", conv_id, msg_id, ts=msg_ts)
        if prev:
            data.edge("NEXT", prev, msg_id, ts=msg_ts)
        prev = msg_id


# --------------------------------------------------------------------------- beta
def generate_beta(rng: random.Random) -> GraphData:
    data = GraphData()
    teams = N.BETA_TEAMS
    owner = {svc: t for t, (_, svcs) in teams.items() for svc in svcs}
    for t, (name, _) in teams.items():
        data.node("Team", id=f"team:{t}", name=name)
    for svc in owner:
        data.node("Service", id=f"svc:{svc}", name=svc, tier=rng.choice([1, 2, 3]), lang=rng.choice(["go", "rust", "python"]))
    members = make_people(rng, data, teams, N.BETA_TEAM_SIZES, N.BETA_NAMED, N.BETA_FIRST, N.BETA_LAST)
    oncall = {}
    for svc, t in owner.items():
        data.edge("OWNS", f"team:{t}", f"svc:{svc}", valid_from=N.BASE_TS, source_doc="doc:service-catalog")
        oncall[f"svc:{svc}"] = "per:lars-eriksen" if svc == "payments-api" else rng.choice(
            [p for p in members[t] if p != "per:lars-eriksen"])
    for s, p in oncall.items():
        data.edge("ON_CALL_FOR", p, s, valid_from=N.BASE_TS, source_doc="doc:oncall-schedule")
    background_depends(rng, data, list(owner), ["storefront", "checkout-web", "payments-api"],
                       [("storefront", "checkout-web"), ("checkout-web", "payments-api")], per_service=(0, 2))
    data.node("Document", id="doc:deploy-log", title="Deploy log", kind="registry", text="Deployment history.", ts=N.BASE_TS, source="seed")
    for svc, t in owner.items():
        deploy(data, svc, f"1.{rng.randint(0, 9)}.0", rand_ts(rng), rng.choice(members[t]), "succeeded")
    for n, svc in enumerate(rng.sample(list(owner), 6), start=1):
        t = owner[svc]
        ts_open = rand_ts(rng)
        incident(data, f"inc:b{n:03d}", f"{svc} errors", svc, "SEV2", ts_open,
                 iso(datetime.strptime(ts_open, "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=1)), None,
                 [rng.choice(members[t])], f"{svc} returned errors for an hour.")
    for n, t in enumerate(["core", "web", "data"], start=1):
        svc = teams[t][1][0]
        maker = rng.choice(members[t])
        dec_id = f"adr:b{n:02d}"
        data.node("Decision", id=dec_id, title=f"ADR-B{n:02d}: {svc} conventions", ts=rand_ts(rng), status="accepted",
                  rationale=f"Conventions for {svc}.", forbids=[])
        data.edge("MADE", maker, dec_id, source_doc=f"doc:adr-b{n:02d}")
        data.edge("GOVERNS", dec_id, f"svc:{svc}", source_doc=f"doc:adr-b{n:02d}")
    registry_docs(data, teams, members, oncall)
    for dec_id in data.ids("Decision"):
        p = data.nodes[dec_id][1]
        maker = [s for r, s, d, _ in data.edges if r == "MADE" and d == dec_id][0]
        doc(data, f"doc:{dec_id.replace(':', '-')}", p["title"], "adr", p["rationale"], p["ts"], author=maker,
            mentions=[d for r, s, d, _ in data.edges if r == "GOVERNS" and s == dec_id], evidence_for=[dec_id])
    for inc_id in data.ids("Incident"):
        p = data.nodes[inc_id][1]
        resolver = [s for r, s, d, _ in data.edges if r == "RESOLVED" and d == inc_id][0]
        svc = [d for r, s, d, _ in data.edges if r == "AFFECTED" and s == inc_id]
        doc(data, f"doc:pm-{inc_id[4:]}", f"Postmortem: {p['title']}", "postmortem", p["summary"], p["ts_close"],
            author=resolver, mentions=svc + [inc_id], evidence_for=[inc_id])
    data.node("Agent", id="agent:triage", name="Triage", role="triage")
    data.node("Agent", id="agent:remediation", name="Remediation", role="remediation")
    ep_id, ts, question, outcome = N.BETA_MEMORY_EPISODE
    data.node("Episode", id=ep_id, ts=ts, question=question, outcome=outcome)
    data.edge("RAN", "agent:triage", ep_id, ts=ts)
    data.edge("INVOLVED", ep_id, "svc:payments-api", ts=ts)
    return data


def generate(profile: str, seed: int) -> GraphData:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose from {PROFILES}")
    rng = random.Random(f"{profile}:{seed}")
    return generate_acme(rng) if profile == "acme" else generate_beta(rng)


# --------------------------------------------------------------------------- pure-Python mirrors (ground truth)
def expertise_edges(data: GraphData) -> dict[tuple[str, str], int]:
    """Mirror of projections.EXPERTISE_EVIDENCE over in-memory data (used for ground truth and tests)."""
    out = defaultdict(lambda: defaultdict(list))
    for r, s, d, p in data.edges:
        out[r][s].append((d, p))
    w = defaultdict(int)

    def hop(rel, src):
        return [d for d, _ in out[rel][src]]

    for p in data.ids("Person"):
        for i in hop("RESOLVED", p):
            for s in hop("AFFECTED", i):
                w[(p, s)] += 3
        for dep in hop("AUTHORED", p):
            for s in hop("DEPLOYED_TO", dep):
                w[(p, s)] += 2
        for dec in hop("MADE", p):
            for s in hop("GOVERNS", dec):
                w[(p, s)] += 2
        for doc_id in hop("WROTE", p):
            for m in hop("MENTIONS", doc_id):
                if data.label(m) == "Service":
                    w[(p, m)] += 1
        for s, props in out["ON_CALL_FOR"][p]:
            if "valid_to" not in props:
                w[(p, s)] += 1
    return dict(w)


def blast_radius(data: GraphData, svc: str, depth: int = 3) -> list[str]:
    """Services that depend on `svc` within `depth` hops (reverse DEPENDS_ON BFS)."""
    rev = defaultdict(list)
    for r, s, d, p in data.edges:
        if r == "DEPENDS_ON" and "valid_to" not in p:
            rev[d].append(s)
    seen, frontier = set(), [svc]
    for _ in range(depth):
        frontier = [s for f in frontier for s in rev[f] if s not in seen and s != svc]
        seen.update(frontier)
    return sorted(seen)


def shortest_path(data: GraphData, src: str, dst: str) -> list[str]:
    nxt = defaultdict(list)
    for r, s, d, p in data.edges:
        if r == "DEPENDS_ON" and "valid_to" not in p:
            nxt[s].append(d)
    prev, q = {src: None}, deque([src])
    while q:
        n = q.popleft()
        if n == dst:
            path = []
            while n:
                path.append(n)
                n = prev[n]
            return path[::-1]
        for m in sorted(nxt[n]):
            if m not in prev:
                prev[m] = n
                q.append(m)
    return []


def pagerank_top(data: GraphData, k: int = 3, damping: float = 0.85, iters: int = 100) -> list[str]:
    svcs = data.ids("Service")
    out = defaultdict(list)
    for r, s, d, p in data.edges:
        if r == "DEPENDS_ON":
            out[s].append(d)
    n = len(svcs)
    pr = {s: 1 / n for s in svcs}
    for _ in range(iters):
        dangling = sum(pr[s] for s in svcs if not out[s])
        nxt = {s: (1 - damping) / n + damping * dangling / n for s in svcs}
        for s in svcs:
            for d in out[s]:
                nxt[d] += damping * pr[s] / len(out[s])
        pr = nxt
    return sorted(svcs, key=lambda s: (-pr[s], s))[:k]


def orphans(data: GraphData) -> list[str]:
    covered = {d for r, s, d, p in data.edges if r in ("OWNS", "ON_CALL_FOR") and "valid_to" not in p}
    return sorted(s for s in data.ids("Service") if s not in covered)


def ground_truth(profile: str, seed: int, data: GraphData) -> dict:
    counts = {
        "nodes": len(data.nodes),
        "edges_loaded": len(data.edges),
        "nodes_by_label": dict(sorted(Counter(label for label, _ in data.nodes.values()).items())),
        "edges_by_type": dict(sorted(Counter(rel for rel, *_ in data.edges).items())),
        "derived_knows": len(expertise_edges(data)),
    }
    gt = {"profile": profile, "seed": seed, "counts": counts}
    if profile == "beta":
        gt["scenario8"] = {
            "service": "svc:payments-api",
            "owner_team": "team:core",
            "on_call": "per:lars-eriksen",
            "episode": "ep:b0001",
            "beta_only_ids": sorted(i for i in data.nodes if i.startswith(("per:", "team:", "inc:", "adr:", "ep:"))),
        }
        return gt
    stale = sorted(
        d for r, d, dec, _ in data.edges
        if r == "MENTIONS" and data.label(dec) == "Decision" and data.nodes[d][1]["kind"] == "runbook"
        and any(e[0] == "SUPERSEDES" and e[2] == dec for e in data.edges)
    )
    gt.update({
        "scenario1": {
            "service": "svc:payments-api",
            "blast_radius_3": blast_radius(data, "svc:payments-api", 3),
            "owner_team": "team:payments",
            "on_call": "per:arjun-mehta",
            "last_deploy": "dep:payments-api@2.14.0",
            "last_deploy_author": "per:kavya-rao",
            "prior_incident": "inc:0042",
            "prior_incident_cause": "dep:payments-api@2.12.0",
            "postmortem": "doc:pm-0042",
        },
        "scenario2": {
            "service": "svc:orders-api",
            "decision_trail": ["adr:019", "adr:007"],
            "current_decision": "adr:019",
            "sources": ["doc:adr-019", "doc:adr-007"],
            "stale_runbooks": [d for d in stale if d == "doc:rb-orders-retry"],
            "action": {"kind": "change_retry_policy", "target": "svc:orders-api", "allowed": False, "blocked_by": "adr:019"},
        },
        "scenario3": {
            "service": "svc:billing-batch",
            "on_call": None,
            "owner_team": "team:ledger",
            "orphans": orphans(data),
        },
        "scenario4": {"key_people_top2": ["per:dev-malhotra", "per:priya-nair"]},
        "scenario5": {"episode": "ep:0001", "lesson": "lesson:pool-exhaustion", "procedure": "proc:rollback-payments",
                      "conversation": "conv:0001", "messages": 4},
        "scenario6": {"agents": ["agent:remediation", "agent:triage"], "handoffs_seeded": 0},
        "scenario7": {"service": "svc:billing-batch", "owner_before": "team:ledger", "owner_after": "team:atlas",
                      "source_before": "doc:service-catalog", "ingest_doc": "chat:billing-move"},
        "scenario7b": {"stale_runbooks_after_move": [d for d in stale if d == "doc:rb-billing-rerun"]},
        "stale_runbooks": stale,
        "eval": {
            "A1": blast_radius(data, "svc:payments-api", 3),
            "A2": shortest_path(data, "svc:checkout-web", "svc:payments-api"),
            "A3": pagerank_top(data, 3),
            "A4": orphans(data),
            "A5": ["adr:019", "blocked"],
        },
    })
    return gt


# --------------------------------------------------------------------------- loader
BATCH = 500


def load(tenant: str, data: GraphData) -> dict:
    """Replace the tenant's graph with `data`, create indexes, rebuild projections."""
    from backend.app.graph.client import get_db
    from backend.app.graph.indexes import ensure_indexes
    from backend.app.graph.projections import refresh_projections
    from backend.app.graph.tenant import get_graph, graph_name

    if graph_name(tenant) in get_db().list_graphs():
        get_graph(tenant).delete()
    graph = get_graph(tenant)
    ensure_indexes(graph)

    by_label = defaultdict(list)
    for label, props in data.nodes.values():
        by_label[label].append(props)
    for label, rows in by_label.items():
        assert label in schema.NODE_LABELS  # only schema labels are ever interpolated
        for i in range(0, len(rows), BATCH):
            graph.query(f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row", {"rows": rows[i:i + BATCH]})

    by_shape = defaultdict(list)
    for rel, src, dst, props in data.edges:
        by_shape[(rel, data.label(src), data.label(dst))].append({"src": src, "dst": dst, "props": props})
    for (rel, sl, dl), rows in by_shape.items():
        assert rel in schema.EDGE_TYPES and sl in schema.NODE_LABELS and dl in schema.NODE_LABELS
        q = (f"UNWIND $rows AS row MATCH (a:{sl} {{id: row.src}}) MATCH (b:{dl} {{id: row.dst}}) "
             f"CREATE (a)-[r:{rel}]->(b) SET r += row.props")
        for i in range(0, len(rows), BATCH):
            graph.query(q, {"rows": rows[i:i + BATCH]})

    derived = refresh_projections(graph)
    nodes = graph.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
    edges = graph.ro_query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0]
    return {"graph": graph_name(tenant), "nodes": nodes, "edges": edges, "derived": derived}


def write_ground_truth(tenant: str, gt: dict, path: Path = GROUND_TRUTH_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing[tenant] = gt
    path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed a Triveni tenant graph with deterministic synthetic data.")
    ap.add_argument("--tenant", required=True, help="tenant name; graph is tenant_<name>")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--profile", choices=PROFILES, help="data profile (defaults to the tenant name)")
    ap.add_argument("--dry-run", action="store_true", help="generate + ground truth only, do not touch FalkorDB")
    args = ap.parse_args()
    profile = args.profile or args.tenant
    data = generate(profile, args.seed)
    gt = ground_truth(profile, args.seed, data)
    write_ground_truth(args.tenant, gt)
    print(f"generated {profile} (seed {args.seed}): {gt['counts']['nodes']} nodes, "
          f"{gt['counts']['edges_loaded']} edges + ~{2 * gt['counts']['derived_knows']} derived KNOWS/KNOWN_BY")
    if not args.dry_run:
        print(load(args.tenant, data))


if __name__ == "__main__":
    main()
