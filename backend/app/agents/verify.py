"""Deterministic proof check of an agent answer (all tracks). Code, not a model, has the last word.

Every entity id and source the answer cites is checked against two things:
  1. the graph: does the entity exist in this tenant?            (no  -> "unknown": an invented id)
  2. the evidence: did a tool in this run return it?              (no  -> "unbacked": exists, but not shown by a tool)
Everything else is "grounded". The verdict is "verified" only when every citation is grounded.
"""
import re

from falkordb import Graph

ID_RE = re.compile(r"\b(?:svc|per|team|inc|adr|doc|ep|lesson|proc|handoff|action|dep|conv):[A-Za-z0-9][A-Za-z0-9@._-]*")
EXISTS = "MATCH (n) WHERE n.id IN $ids RETURN n.id"


def cited_ids(answer: str) -> list[str]:
    seen = []
    for m in ID_RE.findall(answer or ""):
        m = m.rstrip(".,;:)")
        if m not in seen:
            seen.append(m)
    return seen


def evidence_ids(text: str) -> set[str]:
    """Every id that appears anywhere in a tool result (data, paths, sources)."""
    return {m.rstrip(".,;:)") for m in ID_RE.findall(text or "")}


def verify(graph: Graph, answer: str, evidence: set[str]) -> dict:
    cited = cited_ids(answer)
    existing = {r[0] for r in graph.ro_query(EXISTS, {"ids": cited}).result_set} if cited else set()
    grounded = [i for i in cited if i in existing and i in evidence]
    unbacked = [i for i in cited if i in existing and i not in evidence]
    unknown = [i for i in cited if i not in existing]
    verdict = ("no_citations" if not cited else "verified" if len(grounded) == len(cited)
               else "unverified" if unknown else "partially_verified")
    return {"verdict": verdict, "cited": len(cited), "grounded": grounded, "unbacked": unbacked, "unknown": unknown,
            "method": "every cited id must exist in the tenant graph and appear in a tool result from this run"}
