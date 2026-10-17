"""Triveni HTTP API (FastAPI). The UI talks only to this; every answer carries provenance.

    uvicorn backend.app.main:app --reload
"""
import os
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.agents.loop import run_agent
from backend.app.agents.triage import SYSTEM as TRIAGE_SYSTEM
from backend.app.graph.client import ping
from backend.app.graph.tenant import InvalidTenant, get_graph, graph_name, list_tenants
from backend.app.llm.providers import provider_order
from backend.app.memory.conversation import list_conversations, load_history
from backend.app.actions.actions import decide, list_actions
from backend.app.agents.remediation import run_once as run_remediation
from backend.app.coordination.handoff import list_handoffs
from backend.app.tools import REGISTRY, run_tool

load_dotenv()
app = FastAPI(title="Triveni", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("TRIVENI_CORS_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001").split(","),
    allow_methods=["*"], allow_headers=["*"],
)


def tenant_graph(tenant: str):
    try:
        graph_name(tenant)
    except InvalidTenant as exc:
        raise HTTPException(400, str(exc)) from exc
    if tenant not in list_tenants():
        raise HTTPException(404, f"unknown tenant {tenant!r}")
    return get_graph(tenant)


# --------------------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    providers = provider_order()  # e.g. ["groq", "gemini", "rules"]; rules (no model) is always last
    return {"falkordb": ping(), "agent": True, "providers": providers, "model_backed": providers[0] != "rules",
            "demo_replay": os.getenv("DEMO_REPLAY") == "1"}


@app.get("/api/tenants")
def tenants():
    return [t for t in list_tenants() if not t.startswith(("test_", "dbg_", "eval_", "conc_")) and "__whatif" not in t]


@app.get("/api/tools")
def tools():
    return [{"name": t.name, "description": t.description, "input_schema": t.input_schema,
             "tracks": list(t.tracks), "read_only": t.read_only} for t in REGISTRY.values()]


# --------------------------------------------------------------------------- tools and agent
class ToolCall(BaseModel):
    tenant: str
    args: dict = Field(default_factory=dict)


@app.post("/api/tools/{name}")
def call_tool(name: str, body: ToolCall):
    tenant_graph(body.tenant)
    if name not in REGISTRY:
        raise HTTPException(404, f"unknown tool {name!r}")
    try:
        return run_tool(body.tenant, name, body.args).to_dict()
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(400, f"{type(exc).__name__}: {exc}") from exc


class Ask(BaseModel):
    tenant: str
    question: str = Field(min_length=3, max_length=2000)
    conversation_id: str | None = Field(default=None, pattern=r"^conv:[a-z0-9-]+$")
    user_id: str = Field(default="user:demo", pattern=r"^user:[a-z0-9-]+$")
    run_id: str | None = Field(default=None, pattern=r"^run:[a-z0-9-]{4,40}$")  # lets the UI poll live status


# Live status of running /api/ask calls, for the UI's "thinking" indicator only. This is display state for one
# HTTP request, not agent state: agents still coordinate only through Handoff nodes in the graph.
PROGRESS: dict[str, dict] = {}
PROGRESS_TTL_S = 300
# Live requests do not wait out rate limits: a limited provider falls through to the next one at once.
UI_MAX_WAIT_S = float(os.getenv("TRIVENI_UI_MAX_WAIT", "0"))


def _progress_recorder(run_id: str | None):
    if run_id is None:
        return None
    now = time.time()
    for key in [k for k, v in PROGRESS.items() if now - v["started"] > PROGRESS_TTL_S]:
        PROGRESS.pop(key, None)
    PROGRESS[run_id] = {"started": now, "done": False, "events": []}

    def record(msg: str) -> None:
        PROGRESS[run_id]["events"].append({"t": round(time.time() - now, 1), "msg": msg})
    return record


@app.post("/api/ask")
async def ask(body: Ask):
    tenant_graph(body.tenant)
    # history is rebuilt from the graph; the answer, the conversation and an episode are written back to it
    try:
        result = await run_agent(body.question, body.tenant, TRIAGE_SYSTEM, conversation_id=body.conversation_id,
                                 user_id=body.user_id, max_wait=UI_MAX_WAIT_S,
                                 progress=_progress_recorder(body.run_id))  # falls back to rules mode if no model answers
    finally:
        if body.run_id in PROGRESS:
            PROGRESS[body.run_id]["done"] = True
    return result.to_dict()


@app.get("/api/ask/progress/{run_id}")
def ask_progress(run_id: str):
    run = PROGRESS.get(run_id)
    if run is None:
        return {"run_id": run_id, "done": False, "events": []}  # not started yet (the poll can beat the POST)
    return {"run_id": run_id, "done": run["done"], "events": run["events"]}


@app.get("/api/conversations")
def conversations(tenant: str):
    return list_conversations(tenant_graph(tenant))


@app.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: str, tenant: str):
    messages = load_history(tenant_graph(tenant), conversation_id)
    if not messages:
        raise HTTPException(404, f"no conversation {conversation_id}")
    return {"id": conversation_id, "messages": messages}


class Ingest(BaseModel):
    tenant: str
    path: str


@app.post("/api/ingest")
def ingest(body: Ingest):
    return call_tool("ingest_document", ToolCall(tenant=body.tenant, args={"path": body.path}))


# --------------------------------------------------------------------------- graph data for the canvas
OVERVIEW = """
MATCH (s:Service)
OPTIONAL MATCH (s)-[d:DEPENDS_ON]->(t:Service) WHERE d.valid_to IS NULL
RETURN s.id, s.name, s.tier, collect(t.id)
"""
OWNERSHIP = "MATCH (t:Team)-[o:OWNS]->(s:Service) WHERE o.valid_to IS NULL RETURN t.id, t.name, s.id"
NODES = """
MATCH (n) WHERE n.id IN $ids
RETURN n.id, labels(n)[0], coalesce(n.name, n.title, n.version, n.id), n.tier, n.kind, n.status
"""


@app.get("/api/graph/overview")
def overview(tenant: str):
    g = tenant_graph(tenant)
    nodes, edges = [], []
    for sid, name, tier, deps in g.ro_query(OVERVIEW).result_set:
        nodes.append({"id": sid, "label": "Service", "name": name, "tier": tier})
        edges += [{"type": "DEPENDS_ON", "source": sid, "target": t} for t in deps if t]
    teams = {}
    for tid, tname, sid in g.ro_query(OWNERSHIP).result_set:
        teams[tid] = tname
        edges.append({"type": "OWNS", "source": tid, "target": sid})
    nodes += [{"id": tid, "label": "Team", "name": name} for tid, name in teams.items()]
    return {"nodes": nodes, "edges": edges}


class NodeIds(BaseModel):
    tenant: str
    ids: list[str] = Field(max_length=500)


@app.post("/api/graph/nodes")
def nodes(body: NodeIds):
    rows = tenant_graph(body.tenant).ro_query(NODES, {"ids": body.ids}).result_set
    return [{"id": i, "label": label, "name": name, "tier": tier, "kind": kind, "status": status}
            for i, label, name, tier, kind, status in rows]


NODE = "MATCH (n {id: $id}) RETURN labels(n)[0], properties(n)"
NODE_EDGES = """
MATCH (n {id: $id})-[r]-(m) WHERE r.derived IS NULL
RETURN type(r), startNode(r) = n, m.id, labels(m)[0], coalesce(m.name, m.title, m.version, m.id),
       r.valid_from, r.valid_to, r.source_doc
LIMIT 200
"""
PEOPLE = "MATCH (p:Person) RETURN p.id, p.name, p.role ORDER BY p.name"


@app.get("/api/graph/node/{node_id}")
def node_detail(node_id: str, tenant: str):
    """One node's properties and its fact edges, current and historical (derived projections left out)."""
    g = tenant_graph(tenant)
    rows = g.ro_query(NODE, {"id": node_id}).result_set
    if not rows:
        raise HTTPException(404, f"no node {node_id}")
    label, props = rows[0]
    props = {k: (v[:400] + "…" if isinstance(v, str) and len(v) > 400 else v) for k, v in props.items()}
    edges = [{"type": t, "out": out, "id": mid, "label": mlabel, "name": mname,
              "valid_from": vf, "valid_to": vt, "source_doc": src}
             for t, out, mid, mlabel, mname, vf, vt, src in g.ro_query(NODE_EDGES, {"id": node_id}).result_set]
    return {"id": node_id, "label": label, "properties": props, "edges": edges}


@app.get("/api/people")
def people(tenant: str):
    return [{"id": i, "name": n, "role": r} for i, n, r in tenant_graph(tenant).ro_query(PEOPLE).result_set]


@app.get("/api/documents/{doc_id}")
def document(doc_id: str, tenant: str):
    rows = tenant_graph(tenant).ro_query(
        """MATCH (d:Document {id: $id})
           OPTIONAL MATCH (a:Person)-[:WROTE]->(d)
           OPTIONAL MATCH (d)-[:MENTIONS]->(m)
           RETURN d.id, d.title, d.kind, d.ts, d.source, d.text, a.name, collect(m.id)""",
        {"id": doc_id}).result_set
    if not rows:
        raise HTTPException(404, f"no document {doc_id}")
    i, title, kind, ts, source, text, author, mentions = rows[0]
    return {"id": i, "title": title, "kind": kind, "ts": ts, "source": source, "text": text,
            "author": author, "mentions": [m for m in mentions if m]}


# --------------------------------------------------------------------------- coordination and approvals
@app.get("/api/handoffs")
def handoffs(tenant: str):
    return list_handoffs(tenant_graph(tenant))


@app.get("/api/actions")
def actions(tenant: str):
    return list_actions(tenant_graph(tenant))


class Decision(BaseModel):
    tenant: str
    person: str = Field(pattern=r"^per:[a-z0-9-]+$")  # the human approving or rejecting
    approve: bool


@app.post("/api/actions/{action_id}/decide")
def decide_action(action_id: str, body: Decision):
    try:
        return decide(tenant_graph(body.tenant), action_id, body.person, body.approve)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


class RunRemediation(BaseModel):
    tenant: str


@app.post("/api/remediation/run")
async def remediation(body: RunRemediation):
    """Start the remediation agent once: it claims the next open handoff from the graph (if any) and works on it."""
    tenant_graph(body.tenant)
    handoff, result = await run_remediation(body.tenant)
    return {"handoff": handoff, "result": result.to_dict() if result else None}
