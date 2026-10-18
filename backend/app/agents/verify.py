"""Deterministic proof check of an agent answer (all tracks). Code, not a model, has the last word.

Every entity the answer refers to is found, by id ("per:arjun-mehta") or by name ("Arjun Mehta", "payments-api",
"Team Ledger"), using the tenant's own graph as the dictionary. Each one is then checked against two things:
  1. the graph: does the entity exist in this tenant?        (no  -> "unknown": an invented id or name)
  2. the evidence: did a tool in this run return it, or did the user name it?   (no -> "unbacked")
Everything else is "grounded". The verdict is "verified" only when every reference is grounded.

Invented names are caught without a model too: a service-like slug whose suffix is one this tenant uses ("-api",
"-worker", ...) but which names no service, and a "First Last" pair built from real first/last names that is not a
person, are reported as unknown.

The agent loop acts on the verdict (`guard`): an answer with unknown or unbacked references is not shown as the
answer. It is replaced by one composed only from the tool results, and the draft is kept for inspection.
"""
import re
from dataclasses import dataclass

from falkordb import Graph

ID_RE = re.compile(r"\b(?:svc|per|team|inc|adr|doc|ep|lesson|proc|handoff|action|dep|conv):[A-Za-z0-9][A-Za-z0-9@._-]*")
EXISTS = "MATCH (n) WHERE n.id IN $ids RETURN n.id"
LEXICON = "MATCH (n) WHERE n:Service OR n:Person OR n:Team RETURN n.id, n.name, labels(n)[0]"
SLUG_RE = re.compile(r"(?<![\w:/.-])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?![\w-])")
PAIR_RE = re.compile(r"\b([A-Z][a-z]+) ([A-Z][a-z]+)\b")


# Unicode hyphens and dashes that models put inside ids and names (gpt-oss writes "payments‑api"): all become "-"
DASHES = str.maketrans({c: "-" for c in "‐‑‒–—−﹣－"})


def normalize_dashes(text: str) -> str:
    return (text or "").translate(DASHES).replace("­", "")  # soft hyphens are dropped


def _clean(m: str) -> str:
    return m.rstrip(".,;:)")


def cited_ids(answer: str) -> list[str]:
    seen = []
    for m in ID_RE.findall(answer or ""):
        if (m := _clean(m)) not in seen:
            seen.append(m)
    return seen


def evidence_ids(text: str) -> set[str]:
    """Every id that appears anywhere in a tool result (data, paths, sources)."""
    return {_clean(m) for m in ID_RE.findall(text or "")}


@dataclass
class Lexicon:
    """Names of the tenant's services, people and teams, used to find references written as plain names."""
    by_id: dict[str, tuple[str, str]]  # id -> (name, label)
    service_suffixes: set[str]
    first_names: set[str]
    last_names: set[str]

    @classmethod
    def load(cls, graph: Graph) -> "Lexicon":
        by_id = {i: (n, lb) for i, n, lb in graph.ro_query(LEXICON).result_set if i and n}
        services = [n for n, lb in by_id.values() if lb == "Service"]
        people = [n.split() for n, lb in by_id.values() if lb == "Person" and len(n.split()) == 2]
        return cls(by_id, {s.rsplit("-", 1)[-1] for s in services if "-" in s},
                   {p[0] for p in people}, {p[1] for p in people})

    def mentions(self, text: str, bare_teams: bool = False) -> list[tuple[str, str]]:
        """(id, matched text) for every service, person or team named in `text`, in order of appearance.
        Team names are common words ("Search", "Payments"), so in answers only "Team X" / "X team" count;
        `bare_teams` also accepts a capitalized bare team name (used for tool text, which is evidence, not a claim)."""
        found = []
        for nid, (name, label) in self.by_id.items():
            if label == "Team" and bare_teams:
                pattern = rf"\b{re.escape(name)}\b"
            elif label == "Team":
                pattern = rf"(?i:\bteam\s+{re.escape(name)}\b|\b{re.escape(name)}\s+team\b)"
            elif label == "Service":
                pattern = rf"(?<![\w:/.-]){re.escape(name)}(?![\w-])"
            else:
                pattern = rf"\b{re.escape(name)}\b"
            if m := re.search(pattern, text or ""):
                found.append((m.start(), nid, m.group(0)))
        return [(nid, txt) for _, nid, txt in sorted(found)]

    def invented(self, text: str, allowed_text: str) -> list[str]:
        """Names that look like this tenant's services or people but are neither (and the user did not write them)."""
        names = {n.lower() for n, _ in self.by_id.values()}
        out = []
        for slug in SLUG_RE.findall(text or ""):
            if (slug.rsplit("-", 1)[-1] in self.service_suffixes and slug not in names
                    and slug not in allowed_text.lower() and slug not in out):
                out.append(slug)
        for first, last in PAIR_RE.findall(text or ""):
            pair = f"{first} {last}"
            if ((first in self.first_names and last in self.last_names) and pair.lower() not in names
                    and pair not in allowed_text and pair not in out):
                out.append(pair)
        return out


def claimed_tools(answer: str, tools_run: set[str]) -> list[str]:
    """Tools the answer says it used ("a `why_not` check", "[blast_radius]") that did not run in this run.
    Only names with an underscore, or written as code, are matched: "recall" and "recent" are ordinary words."""
    from backend.app.tools import REGISTRY

    out = []
    for name in REGISTRY:
        written = (rf"\b{name}\b" if "_" in name else rf"[`\[]{name}[`\]]")
        if re.search(written, answer or "") and name not in tools_run and name not in out:
            out.append(name)
    return out


def verify(graph: Graph, answer: str, evidence: set[str], context: str = "", evidence_text: str = "",
           tools_run: set[str] | None = None) -> dict:
    """Check every reference in `answer`. `evidence`: ids returned by tools this run (plus ids the user typed);
    `context`: the question and earlier turns, whose plainly named entities also count as given by the user;
    `evidence_text`: the tool results as text, whose plainly named entities count as returned by a tool."""
    answer = normalize_dashes(answer)
    lex = Lexicon.load(graph)
    evidence = set(evidence) | {nid for nid, _ in lex.mentions(context + " " + evidence_text, bare_teams=True)}
    refs: dict[str, str] = {i: i for i in cited_ids(answer)}  # id -> how it was written
    for nid, txt in lex.mentions(answer):
        refs.setdefault(nid, txt)
    existing = {r[0] for r in graph.ro_query(EXISTS, {"ids": list(refs)}).result_set} if refs else set()
    grounded = [i for i in refs if i in existing and i in evidence]
    unbacked = [i for i in refs if i in existing and i not in evidence]
    unknown = [i for i in refs if i not in existing] + lex.invented(answer, " ".join([context, evidence_text, *evidence]))
    if tools_run is not None:  # claiming a tool that never ran is an unbacked claim, like naming an unseen entity
        unbacked += [f"tool:{t}" for t in claimed_tools(answer, tools_run)]
    total = len(refs) + len(unknown) - len([i for i in refs if i not in existing]) + len(
        [u for u in unbacked if u.startswith("tool:")])
    verdict = ("no_citations" if not total else "verified" if len(grounded) == total
               else "unverified" if unknown else "partially_verified")
    return {"verdict": verdict, "cited": total, "grounded": grounded, "unbacked": unbacked, "unknown": unknown,
            "by_name": sorted(i for i, txt in refs.items() if txt != i),
            "method": "every entity the answer names (by id or by name) must exist in the tenant graph and appear in "
                      "a tool result from this run or in the question"}


def guard(verification: dict) -> str | None:
    """Why the answer must not be shown as-is (None when it may): unknown or unbacked references are rejected."""
    if verification["unknown"]:
        return "names entities that are not in the graph: " + ", ".join(verification["unknown"])
    if verification["unbacked"]:
        return "names entities no tool returned in this run: " + ", ".join(verification["unbacked"])
    return None
