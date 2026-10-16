"""Ingestion pipeline: read -> extract (LLM, cached) -> merge -> refresh projections.

    python -m backend.app.ingest.pipeline data/raw/*.md --tenant acme
"""
import argparse
import glob
import json

from backend.app.graph.projections import refresh_projections
from backend.app.graph.tenant import get_graph
from backend.app.ingest.extract import Extraction, extract, read_document
from backend.app.ingest.merge import apply


def ingest(tenant: str, path: str, extraction: Extraction | None = None, refresh: bool = False) -> dict:
    """Ingest one document into `tenant`. Pass `extraction` to skip the LLM (tests, replays)."""
    graph = get_graph(tenant)
    doc = read_document(path)
    origin = "given"
    if extraction is None:
        extraction, origin = extract(doc, graph, refresh=refresh)
    report = apply(graph, doc, extraction)
    report["extracted_by"] = origin
    report["projections"] = refresh_projections(graph)  # keep KNOWS / RESPONSIBLE_FOR current
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest documents into a Triveni tenant graph.")
    ap.add_argument("paths", nargs="+", help="markdown files (globs ok)")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--refresh", action="store_true", help="ignore cached extractions and call the model again")
    args = ap.parse_args()
    for pattern in args.paths:
        for path in sorted(glob.glob(pattern)) or [pattern]:
            report = ingest(args.tenant, path, refresh=args.refresh)
            summary = {k: report[k] for k in ("document", "extracted_by", "entities", "facts", "rejected")}
            print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
