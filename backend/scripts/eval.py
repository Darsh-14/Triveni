"""Per-track eval: Triveni (graph agent over MCP, with memory) vs a flat baseline (TF-IDF over the same documents +
the same model, no graph, no memory). 15 questions, 5 per track, scored by exact match on entity sets.

    python -m backend.scripts.eval --out docs/eval.md

Both systems use the same provider chain (TRIVENI_LLM_PROVIDERS) and must end their answer with
"ENTITIES: ...". Ground truth comes from the seed generator, never from either system.
Questions: notes/eval-questions.md.
"""
import argparse
import json
import os
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import anyio

from backend.app.agents.loop import run_agent
from backend.app.agents.triage import SYSTEM as TRIAGE_SYSTEM
from backend.app.coordination.handoff import create_handoff
from backend.app.graph.tenant import get_graph
from backend.app.ingest.pipeline import ingest
from backend.app.llm.providers import ProviderUnavailable, make, provider_order
from backend.app.memory.conversation import append_message, start_conversation
from backend.app.memory.remember import remember
from backend.scripts import seed

TENANT = "eval_acme"
SUFFIX = ("\n\nAfter your answer, add one final line exactly in this form:\n"
          "ENTITIES: <comma-separated ids (preferred, e.g. svc:orders-api, per:priya-nair, adr:019) or exact names>\n"
          "List ONLY the entities the question asks for (if it asks which services, list only services; if it asks who, "
          "list only people or teams). Do not list supporting evidence such as owners, decisions or source documents "
          "unless the question asks for them.")


@dataclass
class Q:
    id: str
    track: str
    text: str
    gt: str            # key into the context dict holding the expected set
    must: str = ""     # regex the answer must also match (e.g. a "no" for a blocked action)
    conversation: str = ""
    after_ingest: bool = False


QUESTIONS = [
    Q("A1", "01", "If payments-api goes down, which services are affected within 3 hops?", "A1"),
    Q("A2", "01", "What is the shortest dependency path from checkout-web to payments-api? List every service on it.", "A2"),
    Q("A3", "01", "Which 3 services are most critical by dependency structure (most depended upon)?", "A3"),
    Q("A4", "01", "Which services have no owning team and no on-call engineer?", "A4"),
    Q("A5", "01", "Can we change the retry policy on orders-api? If not, which decision blocks it?", "A5",
      must=r"\b(no|not|cannot|can't|blocked|forbid)"),
    Q("B1", "02", "payments-api has connection timeouts again. Have we seen this before? Which past episode and which "
                  "procedure apply?", "B1"),
    Q("B2", "02", "What lesson did we learn the last time payments-api failed?", "B2"),
    Q("B3", "02", "orders-api is slow again. Which procedure worked before?", "B3"),
    Q("B4", "02", "Which open handoffs are waiting for the remediation agent, and about which incident?", "B4"),
    Q("B5", "02", "What team did I say I'm on?", "B5", conversation="B5"),
    Q("C1", "03", "Who owns payments-api and who is on call for it?", "C1"),
    Q("C2", "03", "Which decision governs orders-api today, and which earlier decision did it replace?", "C2"),
    Q("C3", "03", "Who are the two engineers whose departure would cut knowledge links between teams?", "C3"),
    Q("C4", "03", "Who owns billing-batch now, and who owned it before?", "C4", after_ingest=True),
    Q("C5", "03", "Which runbooks are out of date for the services Team Atlas now owns?", "C5", after_ingest=True),
]


# --------------------------------------------------------------------------- setup + ground truth
def setup() -> dict:
    """Fresh eval tenant, plus the 'earlier sessions' the Track 02 questions depend on. Returns ground truth."""
    data = seed.generate("acme", 42)
    gt = seed.ground_truth("acme", 42, data)
    seed.load(TENANT, data)
    g = get_graph(TENANT)
    s3 = remember(g, "agent:triage", "orders-api slow (inc:0057), worker queue backing up", "resolved",
                  ["inc:0057", "svc:orders-api"], lesson="Scale orders-api workers when queue depth grows.",
                  procedure={"name": "Scale orders-api workers", "steps": ["Raise worker pool", "Watch queue depth"]},
                  procedure_result="success")
    h = create_handoff(g, "agent:triage", "inc:0057", "orders-api p99 above 4s, workers saturated", "Propose a fix")
    cid = start_conversation(g, "user:eval")
    append_message(g, cid, "user", "Hi, I'm on the Payments team. Call me Ravi.")
    append_message(g, cid, "assistant", "Noted, Ravi from the Payments team.")
    return {
        "A1": gt["eval"]["A1"], "A2": gt["eval"]["A2"], "A3": gt["eval"]["A3"], "A4": gt["eval"]["A4"], "A5": ["adr:019"],
        "B1": ["ep:0001", "proc:rollback-payments"], "B2": ["lesson:pool-exhaustion"], "B3": [s3["procedure"]["id"]],
        "B4": [h["id"], "inc:0057"], "B5": ["team:payments"],
        "C1": ["team:payments", "per:arjun-mehta"], "C2": ["adr:019", "adr:007"], "C3": gt["scenario4"]["key_people_top2"],
        "C4": ["team:atlas", "team:ledger"], "C5": ["doc:rb-billing-rerun"],
        "conversations": {"B5": cid},
    }


# --------------------------------------------------------------------------- normalising answers to entity ids
def catalog() -> dict[str, str]:
    """lower-case name/alias -> id, for every entity in the eval tenant."""
    rows = get_graph(TENANT).ro_query("MATCH (n) RETURN n.id, labels(n)[0], coalesce(n.name, n.title, '')").result_set
    names = {}
    for node_id, label, name in rows:
        if not node_id:
            continue
        names[node_id.lower()] = node_id
        if name:
            names[name.lower()] = node_id
            if label == "Team":
                names[f"team {name.lower()}"] = node_id
            if label == "Decision" and (m := re.match(r"(ADR-\d+)", name)):
                names[m.group(1).lower()] = node_id
    return names


def entities(answer: str, names: dict[str, str]) -> set[str]:
    line = next((ln for ln in reversed(answer.splitlines()) if ln.strip().upper().startswith("ENTITIES")), "")
    out = set()
    for tok in re.split(r"[,;]", line.split(":", 1)[1] if ":" in line else ""):
        tok = tok.strip().strip("`*[]()'\". ").lower()
        if not tok:
            continue
        if tok in names:
            out.add(names[tok])
        elif m := re.fullmatch(r"adr[- ]?(\d+)", tok):
            out.add(f"adr:{int(m.group(1)):03d}")
        else:
            out.add(tok)  # unknown token stays: it makes the set wrong, as it should
    return out


# --------------------------------------------------------------------------- the two systems
@dataclass
class Answer:
    system: str
    question: str
    answer: str
    predicted: list[str]
    expected: list[str]
    correct: bool
    f1: float
    evidence: bool
    seconds: float
    model: str
    tools: list[str] = field(default_factory=list)
    error: str = ""
    tokens: int = 0


class QuotaExhausted(RuntimeError):
    """Every model provider refused (rate limit / quota). The eval stops instead of scoring throttled answers."""


async def triveni(q: Q, ctx: dict) -> tuple[str, bool, str, list[str], int]:
    conv = ctx["conversations"].get(q.conversation) if q.conversation else None
    providers = [make(n) for n in provider_order(include_rules=False)]  # never the rules planner in the eval
    r = await run_agent(q.text + SUFFIX, TENANT, TRIAGE_SYSTEM, conversation_id=conv, persist=False, providers=providers)
    if not r.model or r.answer == "No provider could answer.":
        raise QuotaExhausted("; ".join(f[:160] for f in r.fallbacks))
    evidence = any(s.sources or s.paths for s in r.steps)
    model = r.model + (f" (fell back: {'; '.join(f.split(':')[0] for f in r.fallbacks)})" if r.fallbacks else "")
    return r.answer, evidence, model, [s.tool for s in r.steps], r.tokens


CHUNK_CHARS = 400  # flat RAG retrieves passages, not whole documents (long registry lists would be diluted)


class FlatBaseline:
    """TF-IDF over passages of every Document in the tenant (title + up to ~400 chars of lines), top 8, then the
    same model. No graph, no memory. Chunking keeps long documents (service catalog, deploy log) retrievable."""

    def __init__(self):
        from sklearn.feature_extraction.text import TfidfVectorizer

        rows = get_graph(TENANT).ro_query("MATCH (d:Document) RETURN d.id, d.title, d.text ORDER BY d.id").result_set
        self.docs = []  # passages: (doc id, title, passage text)
        for doc_id, title, text in rows:
            chunk = ""
            for line in (text or "").splitlines():
                if chunk and len(chunk) + len(line) > CHUNK_CHARS:
                    self.docs.append((doc_id, title or "", chunk))
                    chunk = ""
                chunk += line + "\n"
            self.docs.append((doc_id, title or "", chunk))
        self.vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vec.fit_transform([f"{t}\n{x}" for _, t, x in self.docs])

    def retrieve(self, question: str, k: int = 8) -> list[tuple[str, str, str]]:
        scores = (self.matrix @ self.vec.transform([question]).T).toarray().ravel()
        return [self.docs[i] for i in scores.argsort()[::-1][:k]]

    async def answer(self, q: Q) -> tuple[str, bool, str, list[str], int]:
        hits = self.retrieve(q.text)
        context = "\n\n".join(f"[{i}] {t}\n{x}" for i, t, x in hits)
        system = ("You answer questions about an engineering organisation using ONLY the documents below. "
                  "Cite document ids in brackets. If the documents do not contain the answer, say so.")
        user = f"Documents:\n{context}\n\nQuestion: {q.text}{SUFFIX}"
        errors = []
        for name in provider_order(include_rules=False):
            provider = make(name)
            try:
                text, model = await provider.complete(system, user)
                return (text, any(i in text for i, _, _ in hits), model + (f" (fell back: {', '.join(errors)})" if errors else ""),
                        [], getattr(provider, "last_tokens", 0))
            except ProviderUnavailable as exc:
                errors.append(str(exc).split(":")[0])
            finally:
                await provider.client.close()
        raise QuotaExhausted("no model available for the baseline: " + ", ".join(errors))


def question_entities(text: str, names: dict[str, str]) -> set[str]:
    """Entities the question itself names (e.g. "orders-api" in "retry policy on orders-api")."""
    low = text.lower()
    return {i for n, i in names.items() if len(n) > 3 and re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", low)}


def is_correct(predicted: set[str], expected: set[str], asked: set[str], answer: str, must: str) -> bool:
    """All expected entities present; anything extra must be an entity the question named (restating the subject
    is not a wrong answer); plus the `must` pattern if the question has one. The same rule scores both systems."""
    return (expected <= predicted and (predicted - expected) <= asked
            and (not must or bool(re.search(must, answer, re.I))))


def score(system: str, q: Q, ctx: dict, names: dict, fn) -> Answer:
    expected = set(ctx[q.gt])
    t0 = time.perf_counter()
    try:
        text, evidence, model, tools, tokens = anyio.run(fn)
        error = ""
    except QuotaExhausted:
        raise
    except Exception as exc:  # recorded as wrong, never hidden
        text, evidence, model, tools, tokens, error = "", False, "", [], 0, f"{type(exc).__name__}: {exc}"[:300]
    seconds = time.perf_counter() - t0
    predicted = entities(text, names)
    hit = len(predicted & expected)
    f1 = 0.0 if not hit else 2 * hit / (len(predicted) + len(expected))
    correct = is_correct(predicted, expected, question_entities(q.text, names), text, q.must)
    return Answer(system, q.id, text, sorted(predicted), sorted(expected), correct, round(f1, 2), evidence,
                  round(seconds, 1), model, tools, error, tokens)


# --------------------------------------------------------------------------- report
def report(results: list[Answer], started: str, incomplete: str = "") -> str:
    by = {(r.system, r.question): r for r in results}
    models = sorted({r.model.split(" (")[0] for r in results if r.model})
    lines = ["# Eval: Triveni vs flat baseline", "",
             f"Run {started} with `python -m backend.scripts.eval`. 15 questions, 5 per track (notes/eval-questions.md). "
             "Ground truth comes from the seed generator, never from either system. Both systems use the **same model**: "
             f"{', '.join(models) or 'n/a'}. One run, so expect some run-to-run noise.", "",
             "- **Triveni:** the triage agent choosing graph tools over MCP, with memory (episodes, conversation history).",
             f"- **Flat baseline:** TF-IDF over passages (~{CHUNK_CHARS} chars) of the same tenant's documents, top 8, then the "
             "same model. No graph, no memory. It sees the same documents Triveni ingested, including the Scenario 7 chat.", "",
             "**Scoring:** each answer ends with an `ENTITIES:` line, normalised to graph ids. An answer is correct when it "
             "contains every expected entity and its only extras are entities the question itself names (restating the "
             "subject, e.g. `svc:orders-api` in \"retry policy on orders-api\", is not a wrong answer). The same rule scores "
             "both systems. Mean F1 is shown for partial credit. Evidence = the answer is backed by tool provenance "
             "(Triveni) or cites a retrieved document (baseline).", "",
             *([f"> **Incomplete run:** {incomplete}. Free-tier model quotas ran out; the rows below are the questions that "
                "were answered. Re-run when the quota resets.", ""] if incomplete else []),
             "| Track | System | Correct | Mean F1 | Answers with evidence | Median latency | Tokens / answer |",
             "|---|---|---|---|---|---|---|"]
    for track, name in (("01", "Act"), ("02", "Remember & Coordinate"), ("03", "Company Brain")):
        for system in ("Triveni", "Flat baseline"):
            rs = [r for r in results if r.system == system and r.question.startswith({"01": "A", "02": "B", "03": "C"}[track])]
            if not rs:
                continue
            lines.append(f"| {track} {name} | {system} | {sum(r.correct for r in rs)}/{len(rs)} | "
                         f"{statistics.mean(r.f1 for r in rs):.2f} | {round(100 * sum(r.evidence for r in rs) / len(rs))}% | "
                         f"{statistics.median(r.seconds for r in rs):.1f} s | "
                         f"{round(statistics.mean(r.tokens for r in rs)) if any(r.tokens for r in rs) else 'n/a'} |")
    lines += ["", "## Per question", "", "| Q | Expected | Triveni | Baseline | Triveni tools |", "|---|---|---|---|---|"]
    for q in QUESTIONS:
        t, b = by.get(("Triveni", q.id)), by.get(("Flat baseline", q.id))
        if not t or not b:
            continue
        cell = lambda r: ("✅ " if r.correct else "❌ ") + (", ".join(r.predicted) or "(none)") + (f" _{r.error[:60]}_" if r.error else "")
        lines.append(f"| {q.id}: {q.text} | {', '.join(t.expected)} | {cell(t)} | {cell(b)} | {', '.join(t.tools)} |")
    lines += ["", "Models used: " + "; ".join(sorted({f"{r.system}: {r.model}" for r in results if r.model})), "",
              "Notes: B5 is answered from the conversation history the agent loads from the graph, so it has no tool step "
              "(hence Triveni's 80% evidence on Track 02). C1 is a control question the flat baseline is expected to answer "
              "(both owner and on-call are stated in registry documents).", ""]
    return "\n".join(lines)


RESULTS = Path("eval/results.json")


def rescore(out: str) -> None:
    """Apply the current scoring rule to stored answers (no model calls). Needs only the seed's names."""
    seed.load(TENANT, seed.generate("acme", 42))
    names = catalog()
    get_graph(TENANT).delete()
    by_id = {q.id: q for q in QUESTIONS}
    results = []
    for r in (Answer(**x) for x in json.loads(RESULTS.read_text(encoding="utf-8"))):
        q = by_id[r.question]
        pred, exp = set(r.predicted), set(r.expected)
        r.correct = is_correct(pred, exp, question_entities(q.text, names), r.answer, q.must)
        results.append(r)
    RESULTS.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
    md = report(results, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + " (re-scored)")
    Path(out).write_text(md, encoding="utf-8")
    print(md)


def main() -> None:
    ap = argparse.ArgumentParser(description="Triveni per-track eval")
    ap.add_argument("--out", default="docs/eval.md")
    ap.add_argument("--only", help="comma-separated question ids, e.g. A1,C5")
    ap.add_argument("--systems", default="triveni,baseline", help="which systems to run (others are kept from eval/results.json)")
    ap.add_argument("--rescore", action="store_true", help="re-score eval/results.json with the current rule; no model calls")
    ap.add_argument("--pause", type=float, default=float(os.getenv("TRIVENI_EVAL_PAUSE", "20")),
                    help="seconds between model calls (free tiers limit tokens per minute)")
    args = ap.parse_args()
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if args.rescore:
        return rescore(args.out)
    run_systems = {"triveni": "Triveni", "baseline": "Flat baseline"}
    run_systems = {run_systems[x.strip()] for x in args.systems.split(",")}
    ctx = setup()
    names, baseline, ingested, results = catalog(), FlatBaseline(), False, []
    incomplete = ""
    wanted = set(args.only.split(",")) if args.only else None
    for q in QUESTIONS:
        if wanted and q.id not in wanted:
            continue
        if q.after_ingest and not ingested:
            ingest(TENANT, "data/raw/live/chat-billing-move.md")  # cached extraction; same doc goes into the baseline index
            names, baseline, ingested = catalog(), FlatBaseline(), True
        for system, fn in (("Triveni", lambda q=q: triveni(q, ctx)), ("Flat baseline", lambda q=q: baseline.answer(q))):
            if system not in run_systems:
                continue
            try:
                r = score(system, q, ctx, names, fn)
            except QuotaExhausted as exc:
                incomplete = f"stopped at {q.id} ({system}): every model refused: {exc}"
                print(incomplete, flush=True)
                break
            results.append(r)
            print(f"{q.id} {system:13s} {'OK ' if r.correct else 'NO '} pred={r.predicted} exp={r.expected} {r.seconds}s {r.model}",
                  flush=True)
            time.sleep(args.pause)
        if incomplete:
            break
    Path("eval").mkdir(exist_ok=True)
    kept = [Answer(**r) for r in (json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else [])
            if r["system"] not in run_systems]
    results = sorted(kept + results, key=lambda r: ([q.id for q in QUESTIONS].index(r.question), r.system != "Triveni"))
    RESULTS.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
    md = report(results, started, incomplete)
    Path(args.out).write_text(md, encoding="utf-8")
    print(md)
    get_graph(TENANT).delete()


if __name__ == "__main__":
    main()
