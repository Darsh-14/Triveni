"""Triveni HTTP API (FastAPI). The UI talks only to this; every answer carries provenance.

    uvicorn backend.app.main:app --reload
"""
import os

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
    return {"falkordb": ping(), "agent": True, "providers": providers, "model_backed": providers[0] != "rules"}


@app.get("/api/tenants")
def tenants():
    return [t for t in list_tenants() if not t.startswith(("test_", "dbg_"))]


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


@app.post("/api/ask")
async def ask(body: Ask):
    tenant_graph(body.tenant)
    # history is rebuilt from the graph; the answer, the conversation and an episode are written back to it
    result = await run_agent(body.question, body.tenant, TRIAGE_SYSTEM, conversation_id=body.conversation_id,
                             user_id=body.user_id)  # falls back to rules mode if no model answers
    return result.to_dict()


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
