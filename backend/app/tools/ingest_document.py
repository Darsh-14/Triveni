"""ingest_document (Track 03, write tool): turn a raw doc/ticket/chat into graph facts with sources."""
from pathlib import Path

from backend.app.graph.projections import refresh_projections
from backend.app.ingest.extract import extract, read_document
from backend.app.ingest.impact import change_impact
from backend.app.ingest.merge import apply
from backend.app.tools.base import ToolResult, edge_ref, tool

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_ROOT = REPO_ROOT / "data" / "raw"


@tool(
    name="ingest_document",
    description="Ingest a document from data/raw (doc, ticket, chat) into the graph: extract entities and facts into the "
                "fixed schema, merge them with source_doc, and supersede contradicted facts (old edge gets valid_to). "
                "Returns created/closed/unchanged facts and anything rejected.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "path under data/raw, e.g. data/raw/live/chat-billing-move.md"}},
        "required": ["path"],
        "additionalProperties": False,
    },
    tracks=("03",),
    read_only=False,
)
def ingest_document(graph, path: str) -> ToolResult:
    resolved = (REPO_ROOT / path).resolve()
    if RAW_ROOT not in resolved.parents:
        raise ValueError("ingest_document only reads files under data/raw")
    doc = read_document(resolved)
    doc.source = resolved.relative_to(REPO_ROOT).as_posix()
    extraction, origin = extract(doc, graph)
    report = apply(graph, doc, extraction)
    report["projections"] = refresh_projections(graph)
    impact = change_impact(graph, report)
    paths = []
    for f in report["facts"]:
        rel, _, ends = f["fact"].partition(":")
        src, _, dst = ends.partition("->")
        paths.append({"nodes": [src, dst], "edges": [edge_ref(rel, src, dst)]})
        paths += [{"nodes": [old, dst], "edges": [edge_ref(rel, old, dst)], "superseded": True} for old in f["closed"]]
    for imp in impact["impacts"]:
        paths += [{"nodes": [r["document"], r["cites"]], "edges": [edge_ref("MENTIONS", r["document"], r["cites"])], "stale": True}
                  for r in imp["stale_runbooks"]]
        paths += [{"nodes": [c["decision"], imp["service"]], "edges": [edge_ref("GOVERNS", c["decision"], imp["service"])]}
                  for c in imp["constraints"]]
    paths += [{"nodes": [a["id"], a["target"]], "edges": [edge_ref("TARGETS", a["id"], a["target"])]} for a in impact["proposed_actions"]]
    changed = [f["fact"] for f in report["facts"] if f["action"] != "unchanged"]
    return ToolResult(
        data={k: report[k] for k in ("document", "entities", "facts", "rejected")} | {"extracted_by": origin, "impact": impact},
        cypher="\n".join(report["cypher"]), params={"doc": doc.id}, paths=paths,
        sources=sorted({doc.id} | {r["document"] for i in impact["impacts"] for r in i["stale_runbooks"]}),
        explanation=f"Ingested {doc.id}: {len(changed)} fact(s) changed, "
                    f"{sum(len(f['closed']) for f in report['facts'])} superseded, {len(report['rejected'])} rejected."
                    + "".join(f" Impact on {i['service']}: {len(i['stale_runbooks'])} stale runbook(s), "
                              f"{len(i['constraints'])} governing decision(s), "
                              f"{len(i['memory_to_review']['episodes'])} episode(s) to review." for i in impact["impacts"])
                    + (f" Proposed {len(impact['proposed_actions'])} notify_owner action(s) for approval." if impact["proposed_actions"] else ""),
        tracks=["03", "02", "01"] if impact["impacts"] else ["03"],
    )
