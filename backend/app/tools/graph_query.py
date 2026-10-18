"""graph_query (Track 01 / 03): a guarded, read-only Cypher query written by the model. LAST RESORT.

For questions no fixed tool answers ("which tier-1 services depend on more than five others?", "who authored the most
deployments that caused incidents?"). Every other tool runs human-written queries; this one runs the model's, so it
is fenced in:
  1. FalkorDB enforces it: the query goes through GRAPH.RO_QUERY, which rejects any write at the server
     ("graph.RO_QUERY is to be executed only on read-only queries", checked against the live database).
  2. Static checks before it is sent: one statement; it must start with MATCH / OPTIONAL MATCH / WITH / UNWIND /
     RETURN; no CREATE, MERGE, SET, DELETE, REMOVE, DROP, FOREACH, LOAD CSV or CALL.
  3. Every label and relationship type it names must exist in the schema: an invented one is refused, not run.
  4. A row cap (LIMIT added or lowered to 50) and a 3 s server-side timeout.
  5. The tenant is the graph it runs on; the model cannot name another graph.
The result carries the exact query, so the UI shows it in the Cypher drawer marked as model-written, and the ids it
returns become evidence for the proof check like any other tool's.
"""
import re

from backend.app.graph import schema
from backend.app.tools.base import ToolResult, edge_ref, tool

MAX_ROWS = 50
TIMEOUT_MS = 3000
FORBIDDEN = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|FOREACH|LOAD\s+CSV|CALL)\b", re.IGNORECASE)
START = re.compile(r"^\s*(OPTIONAL\s+MATCH|MATCH|WITH|UNWIND|RETURN)\b", re.IGNORECASE)
LABEL_RE = re.compile(r":\s*`?([A-Z][A-Za-z]*)`?")  # (n:Service), (:Person), n:Person in WHERE; run outside [...]
REL_RE = re.compile(r"\[\s*\w*\s*:\s*([A-Z_|`:\s]+?)\s*(?:\*|\{|\]|\s)")  # [r:OWNS|ON_CALL_FOR*1..3]
LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.IGNORECASE)

SCHEMA_HINT = (  # fact edges only, compact: every model round pays for these tokens against free-tier limits
    "Schema: " + ", ".join(f"{t}({'|'.join(sorted(e.sources))}>{'|'.join(sorted(e.targets))})"
                           for t, e in schema.EDGE_TYPES.items() if e.category in (schema.STATE, schema.EVENT))
    + ". Ids: svc:x, per:x, team:x, inc:0042, adr:019. Current state edges: WHERE r.valid_to IS NULL. "
    "(A)-[:DEPENDS_ON]->(B): A needs B. Service.tier, .lang; Incident.severity, .ts_open; Deployment.version, .ts, "
    ".status. No EXISTS{} subqueries: use OPTIONAL MATCH + count(x)=0, or WHERE NOT (s)<-[:REL]-(). "
    "Count with count(DISTINCT x), not rows. For 'most'/'top' return the top 5 with their counts so ties show."
)


class UnsafeQuery(ValueError):
    pass


def _strip(text: str) -> str:
    """Comments and string literals removed, so checks look only at the query's structure."""
    text = re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", text)


HOP_RE = re.compile(r"\((\w*)\s*(?::\s*(\w+))?[^()]*\)\s*(<?)-\[([^\]]*)\]-(>?)(?=\s*\((\w*)\s*(?::\s*(\w+))?)")


def direction_problems(bare: str) -> list[str]:
    """Relationships used backwards or between labels they never connect, e.g. (d:Deployment)-[:CAUSED_BY]->(i:Incident)
    when CAUSED_BY goes Incident -> Deployment. Such a query would run and return nothing, which reads like absence."""
    labels_of = {v: lb for v, lb in re.findall(r"\((\w+)\s*:\s*(\w+)", bare)}
    out = []
    for lvar, llab, back, rel, fwd, rvar, rlab in HOP_RE.findall(bare):
        left, right = llab or labels_of.get(lvar), rlab or labels_of.get(rvar)
        types = [t for t in re.split(r"[|:\s`*]+", rel.split(":", 1)[1]) if t in schema.EDGE_TYPES] if ":" in rel else []
        if not (left and right and types) or (back and fwd) or not (back or fwd):
            continue  # unknown endpoint labels, untyped or undirected hop: nothing to check
        src, dst = (right, left) if back else (left, right)
        if any(src in schema.EDGE_TYPES[t].sources and dst in schema.EDGE_TYPES[t].targets for t in types):
            continue
        for t in types:
            e = schema.EDGE_TYPES[t]
            if dst in e.sources and src in e.targets:
                out.append(f"{t} goes ({'|'.join(sorted(e.sources))})-[:{t}]->({'|'.join(sorted(e.targets))}); "
                           f"the query has it from {src} to {dst}")
            else:
                out.append(f"{t} never connects {src} and {dst}")
    return out


def check(cypher: str) -> str:
    """Validate a model-written query and return it with a row cap. Raises UnsafeQuery with the reason."""
    q = re.sub(r"//[^\n]*|/\*.*?\*/", " ", cypher, flags=re.DOTALL).strip().rstrip(";").strip()  # comments never sent
    bare = _strip(q)
    if ";" in bare:
        raise UnsafeQuery("one statement only")
    if not START.match(bare):
        raise UnsafeQuery("a read query must start with MATCH, OPTIONAL MATCH, WITH, UNWIND or RETURN")
    if m := FORBIDDEN.search(bare):
        raise UnsafeQuery(f"{m.group(1).upper()} is not allowed: this tool only reads")
    outside_rels = re.sub(r"\[[^\[\]]*\]", "[]", bare)  # relationship types live in [...]; labels everywhere else
    unknown_labels = sorted({lb for lb in LABEL_RE.findall(outside_rels) if lb not in schema.NODE_LABELS})
    rels = {t.strip("` ") for group in REL_RE.findall(bare) for t in re.split(r"[|:]", group) if t.strip("` ")}
    unknown_rels = sorted({t for t in rels if t not in schema.EDGE_TYPES})
    if unknown_labels or unknown_rels:
        raise UnsafeQuery("not in the schema: " + ", ".join(unknown_labels + unknown_rels))
    if problems := direction_problems(bare):
        raise UnsafeQuery("; ".join(problems))
    if m := LIMIT_RE.search(bare):
        if int(m.group(1)) > MAX_ROWS:
            q = LIMIT_RE.sub(f"LIMIT {MAX_ROWS}", q)
    elif re.search(r"\bRETURN\b", bare, re.IGNORECASE):
        q = f"{q}\nLIMIT {MAX_ROWS}"
    return q


def rewrite(q: str) -> tuple[str, list[str]]:
    """Two deterministic fixes for the commonest model mistakes, each reported, never silent:
    count(x) over a bare variable counts rows, not things (one deployment that caused two incidents counts twice), so
    it becomes count(DISTINCT x); a ranking cut to fewer than 5 rows hides ties, so the limit is raised to 5."""
    notes = []
    fixed = re.sub(r"\bcount\(\s*(?!DISTINCT\b)([A-Za-z_]\w*)\s*\)", r"count(DISTINCT \1)", q, flags=re.IGNORECASE)
    if fixed != q:
        notes.append("count(x) -> count(DISTINCT x): count things, not rows")
    if re.search(r"\bORDER\s+BY\b", fixed, re.IGNORECASE) and (m := LIMIT_RE.search(fixed)) and int(m.group(1)) < 5:
        fixed = LIMIT_RE.sub("LIMIT 5", fixed)
        notes.append(f"LIMIT {m.group(1)} -> LIMIT 5 on a ranking, so ties show")
    return fixed, notes


def _plain(value, ids: list, paths: list):
    """FalkorDB result values -> JSON-friendly values; node ids and path edges are collected as evidence."""
    cls = type(value).__name__
    if cls == "Node":
        props = dict(value.properties)
        if props.get("id"):
            ids.append(props["id"])
        keep = {k: v for k, v in props.items() if k in ("id", "name", "title", "version", "tier", "lang", "status",
                                                          "severity", "ts", "ts_open", "kind", "role")}
        return {"label": (value.labels or ["?"])[0], **keep}
    if cls == "Path":
        raw = value.nodes()
        nodes = [_plain(n, ids, paths) for n in raw]
        node_ids = [n.get("id") for n in nodes]
        internal = {n.id: n.properties.get("id") for n in raw}  # FalkorDB internal id -> our id, for edge direction
        edges = []
        for e, a, b in zip(value.edges(), node_ids, node_ids[1:]):
            src = internal.get(getattr(e.src_node, "id", e.src_node), a)
            edges.append(edge_ref(e.relation, src, b if src == a else a))
        paths.append({"nodes": node_ids, "edges": edges})
        return {"nodes": node_ids, "edges": edges}
    if cls == "Edge":
        return {"type": value.relation, **{k: v for k, v in dict(value.properties).items() if k != "derived"}}
    if isinstance(value, list):
        return [_plain(v, ids, paths) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v, ids, paths) for k, v in value.items()}
    if isinstance(value, str) and re.fullmatch(r"(svc|per|team|inc|adr|doc|dep|ep|action|handoff):[\w@.\-]+", value):
        ids.append(value)
    return value


@tool(
    name="graph_query",
    description="LAST RESORT: your own READ-ONLY Cypher when no other tool answers (aggregations, rankings, "
                "multi-condition). Writes rejected; schema-only labels/types; max 50 rows; 3 s. " + SCHEMA_HINT,
    input_schema={
        "type": "object",
        "properties": {
            "cypher": {"type": "string", "description": "one read-only Cypher statement; use $params for values"},
            "params": {"type": "object", "description": "query parameters, e.g. {\"tier\": 1}"},
            "purpose": {"type": "string", "description": "one line: what the query finds and why no other tool does"},
        },
        "required": ["cypher", "purpose"],
        "additionalProperties": False,
    },
    tracks=("01", "03"),
)
def graph_query(graph, cypher: str, purpose: str, params: dict | None = None) -> ToolResult:
    try:
        q = check(cypher)
    except UnsafeQuery as exc:
        return ToolResult(data={"refused": str(exc), "cypher": cypher}, cypher=cypher, params=params or {},
                          explanation=f"Query refused before running: {exc}.", outcome="refused")
    q, rewrites = rewrite(q)
    try:
        result = graph.ro_query(q, params or {}, timeout=TIMEOUT_MS)  # GRAPH.RO_QUERY: the server rejects any write
    except Exception as exc:  # syntax error, unsupported clause, timeout: returned so the model can fix its query
        msg = re.sub(r"\s+", " ", str(exc))[:300]
        return ToolResult(data={"refused": msg, "cypher": q}, cypher=q, params=params or {},
                          explanation=f"FalkorDB rejected the query: {msg}. Nothing was read; fix the query or use another tool.",
                          outcome="refused")
    columns = [h[1] if isinstance(h, (list, tuple)) else str(h) for h in result.header]
    ids, paths = [], []
    rows = [[_plain(v, ids, paths) for v in row] for row in result.result_set]
    ids = list(dict.fromkeys(i for i in ids if i))
    paths += [{"nodes": [i], "edges": []} for i in ids if not any(i in p["nodes"] for p in paths)]
    sources = sorted({i for i in ids if i.startswith("doc:")})
    preview = "; ".join(", ".join(str(v)[:60] for v in row) for row in rows[:5])
    return ToolResult(
        data={"model_written": True, "purpose": purpose, "columns": columns, "rows": rows, "row_count": len(rows),
              "rewrites": rewrites},
        cypher=q, params=params or {}, paths=paths, sources=sources,
        explanation=(f"Model-written read-only query ({purpose}): {len(rows)} row(s)"
                     + (f" [{', '.join(columns)}]: {preview}" if rows else
                        "; an empty result from a model-written query is not proof of absence: check property names "
                        "and values, or answer that this query found nothing") + "."
                     + (f" Rewritten before running: {'; '.join(rewrites)}." if rewrites else "")),
        outcome="answered" if rows else "no_rows",
    )
