"""Deterministic entity resolution: turn what a user or model typed into one node of this tenant's graph, or say why not.

The highest-value guardrail for a graph agent is checking that an entity exists before reasoning about it: an empty
traversal from a misspelled service reads like "nothing is affected", and a plausible name is worse than no answer.
So every tool argument that names an entity goes through `resolve()` first (see tools/base.run_tool).

Matching, in order, all against the graph itself (no model involved):
  1. exact id                     svc:payments-api, inc:0042
  2. exact name                   payments-api, Priya Nair
  3. normalized id or name        "Payments API", "payments_api", "Team Ledger", "ADR-023", "0042", "42"
  4. unique partial person name   "Priya" -> per:priya-nair, only if exactly one person matches
Fuzzy near-misses ("paymnts-api") are never auto-corrected; they are returned as suggestions and the tool does not run.
"""
import difflib
import re
from dataclasses import dataclass, field

from falkordb import Graph

PREFIX = {"Service": "svc", "Person": "per", "Team": "team", "Incident": "inc", "Decision": "adr", "Document": "doc",
          "Deployment": "dep", "Episode": "ep", "Lesson": "lesson", "Procedure": "proc", "Handoff": "handoff",
          "Action": "action", "Conversation": "conv", "Agent": "agent"}
FACT_LABELS = ("Service", "Person", "Team", "Incident", "Decision", "Document", "Deployment")
ANY = FACT_LABELS + ("Episode", "Lesson", "Procedure")

CANDIDATES = "MATCH (n) WHERE labels(n)[0] IN $labels RETURN n.id, coalesce(n.name, n.title), labels(n)[0]"


class UnknownEntity(ValueError):
    def __init__(self, query: str, labels: tuple[str, ...], suggestions: list[dict], ambiguous: bool = False):
        self.query, self.labels, self.suggestions, self.ambiguous = query, labels, suggestions, ambiguous
        kind = "/".join(labels) if len(labels) <= 3 else "entity"
        hint = ("; did you mean " + " or ".join(f"{s['name']} ({s['id']})" for s in suggestions) + "?") if suggestions else ""
        problem = "matches more than one" if ambiguous else "matches no"
        super().__init__(f"'{query}' {problem} {kind} in this tenant's graph{hint or '.'}")


@dataclass
class Resolved:
    id: str
    name: str
    label: str
    how: str  # id | name | normalized | partial_name
    query: str = ""

    def to_dict(self) -> dict:
        return {"query": self.query, "id": self.id, "name": self.name, "label": self.label, "how": self.how}


def norm(text: str) -> str:
    """Case, spacing and punctuation-insensitive form: 'Payments API' -> 'payments-api', 'ADR 023' -> 'adr-023'."""
    t = re.sub(r"[\s_./]+", "-", text.strip().lower())
    return re.sub(r"-+", "-", t).strip("-")


def query_keys(text: str) -> set[str]:
    """The query plus its forms without a leading 'the'/'team'/'service' or a trailing 'service'/'team' word."""
    base = text.strip().lower().removeprefix("#")
    variants = {base, re.sub(r"^(the|team|service)\s+", "", base), re.sub(r"\s+(service|team)$", "", base)}
    keys = {norm(v) for v in variants if v}
    keys |= {k.lstrip("0") or "0" for k in keys if k.isdigit()}
    # "incident 42", "INC-0042", "ADR 19", "decision 19" -> inc-42 / adr-19 (the prefix keeps 42 and 19 unambiguous)
    if m := re.fullmatch(r"(inc|incident|adr|decision)[\s:#-]*0*(\d+)", base):
        prefix = {"incident": "inc", "decision": "adr"}.get(m.group(1), m.group(1))
        keys.add(f"{prefix}-{int(m.group(2))}")
    return keys


def _keys(nid: str, name: str | None) -> set[str]:
    prefix, _, local = nid.partition(":")
    keys = {norm(nid.replace(":", "-")), norm(local)}
    if name:
        keys.add(norm(name))
    if local.isdigit():
        keys.add(local.lstrip("0") or "0")  # inc:0042 also answers to 42
        keys.add(f"{prefix}-{int(local)}")  # ... and to inc-42 / "incident 42"
    return keys


@dataclass
class Catalog:
    """All candidate nodes for some labels, loaded with one read-only query."""
    rows: list[tuple[str, str, str]] = field(default_factory=list)

    @classmethod
    def load(cls, graph: Graph, labels: tuple[str, ...]) -> "Catalog":
        return cls([(i, n or i, lb) for i, n, lb in graph.ro_query(CANDIDATES, {"labels": list(labels)}).result_set if i])


def resolve(graph: Graph, query: str, labels: tuple[str, ...], catalog: Catalog | None = None) -> Resolved:
    q = (query or "").strip()
    if not q:
        raise UnknownEntity(query, labels, [])
    cat = catalog or Catalog.load(graph, labels)
    rows = [r for r in cat.rows if r[2] in labels]
    for how, hit in (("id", lambda r: r[0] == q), ("name", lambda r: r[1] == q)):
        found = [r for r in rows if hit(r)]
        if len(found) == 1:
            return Resolved(*found[0], how=how, query=q)
    qkeys = query_keys(q)
    found = [r for r in rows if qkeys & _keys(r[0], r[1])]
    if len(found) == 1:
        return Resolved(*found[0], how="normalized", query=q)
    if len(found) > 1:
        # "ADR-019" names both the decision and its document (doc:adr-019): the entity wins over its own source
        entities = [r for r in found if r[2] != "Document"]
        if len(entities) == 1:
            return Resolved(*entities[0], how="normalized", query=q)
        raise UnknownEntity(q, labels, [_sugg(r) for r in found[:5]], ambiguous=True)
    # a unique first or last name of a person ("Priya" -> Priya Nair); ambiguous names are refused, not guessed
    if "Person" in labels and re.fullmatch(r"[A-Za-z][A-Za-z'-]+", q):
        people = [r for r in rows if r[2] == "Person" and q.lower() in r[1].lower().split()]
        if len(people) == 1:
            return Resolved(*people[0], how="partial_name", query=q)
        if len(people) > 1:
            raise UnknownEntity(q, labels, [_sugg(r) for r in people[:5]], ambiguous=True)
    raise UnknownEntity(q, labels, suggestions(q, rows))


def suggestions(query: str, rows: list[tuple[str, str, str]], n: int = 3) -> list[dict]:
    by_key = {}
    for r in rows:
        for k in _keys(r[0], r[1]):
            by_key.setdefault(k, r)
    close = difflib.get_close_matches(norm(query), list(by_key), n=n * 2, cutoff=0.72)
    out = []
    for k in close:
        if (s := _sugg(by_key[k])) not in out:
            out.append(s)
    return out[:n]


def _sugg(row: tuple[str, str, str]) -> dict:
    return {"id": row[0], "name": row[1], "label": row[2]}


SPOT_LABELS = ("Service", "Person", "Team", "Incident", "Decision")


def spot(graph: Graph, text: str, catalog: Catalog | None = None) -> list[dict]:
    """Every service, person, team, incident and decision named in free text, in order, without a model.

    Services match with spaces or hyphens ("payments api", "payments-api"); people by full name, or by a first name
    only one person has; teams as "Team X" / "X team"; incidents as inc:0042 / "incident 42" / INC-0042; decisions as
    adr:019 / ADR-019 / "ADR 19". Overlapping matches keep the longest. Used by the rules planner (no model)."""
    cat = catalog or Catalog.load(graph, SPOT_LABELS)
    text = text or ""
    hits = []  # (start, end, row)
    firsts: dict[str, list] = {}
    for row in cat.rows:
        nid, name, label = row
        local = nid.partition(":")[2]
        if label == "Service":
            pats = [r"(?<![\w-])" + r"[\s_-]?".join(re.escape(p) for p in name.split("-")) + r"(?![\w-])"]
        elif label == "Person":
            pats = [r"\b" + r"\s+".join(re.escape(p) for p in name.split()) + r"\b"]
            firsts.setdefault(name.split()[0].lower(), []).append(row)
        elif label == "Team":
            pats = [rf"\bteam\s+{re.escape(name)}\b", rf"\b{re.escape(name)}\s+team\b"]
        elif label == "Incident" and local.isdigit():
            pats = [rf"\binc(?:ident)?[\s:#-]*0*{int(local)}\b"]
        elif label == "Decision" and local.isdigit():
            pats = [rf"\badr[\s:#-]*0*{int(local)}\b"]
        else:
            pats = []
        pats.append(rf"(?<![\w-]){re.escape(nid)}(?![\w-])")
        for pat in pats:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                hits.append((m.start(), m.end(), row))
    for first, rows in firsts.items():  # "Priya" alone, only when exactly one person has that first name
        if len(rows) == 1:
            for m in re.finditer(rf"\b{re.escape(first)}\b", text, flags=re.IGNORECASE):
                if text[m.start()].isupper():
                    hits.append((m.start(), m.end(), rows[0]))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    out, covered_to, seen = [], -1, set()
    for start, end, (nid, name, label) in hits:
        if start < covered_to:  # inside a longer match already taken ("payments-api" vs "payments")
            continue
        covered_to = end
        if nid not in seen:
            seen.add(nid)
            out.append({"id": nid, "name": name, "label": label, "text": text[start:end]})
    return out
