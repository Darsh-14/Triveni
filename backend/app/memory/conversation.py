"""Conversation history in the graph (Track 02): (Conversation)-[:HAS_MESSAGE]->(Message), chained by NEXT.

The process keeps no conversation state. Every request rebuilds the model's context from the graph, so
history survives restarts and is visible to any process that can read the tenant graph.
"""
import uuid
from datetime import datetime, timezone

from falkordb import Graph

START = """
MERGE (c:Conversation {id: $id})
ON CREATE SET c.user_id = $user, c.started_ts = $ts
WITH c
MATCH (a:Agent {id: $agent})
MERGE (c)-[w:WITH]->(a) ON CREATE SET w.ts = $ts
RETURN c.id, c.started_ts
"""

# seq is computed in the same statement that creates the message, and NEXT links it to the previous one
APPEND = """
MATCH (c:Conversation {id: $cid})
OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
WITH c, max(m.seq) AS last
CREATE (c)-[:HAS_MESSAGE {ts: $ts}]->(n:Message {id: $mid, role: $role, text: $text, ts: $ts, seq: coalesce(last, -1) + 1})
WITH c, n
OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(prev:Message {seq: n.seq - 1})
FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | CREATE (prev)-[:NEXT {ts: $ts}]->(n))
RETURN n.seq
"""

# walk the NEXT chain from the first message
HISTORY = """
MATCH (c:Conversation {id: $cid})-[:HAS_MESSAGE]->(first:Message {seq: 0})
MATCH (first)-[:NEXT*0..500]->(m:Message)
RETURN m.role, m.text, m.seq, m.ts
ORDER BY m.seq
"""

LIST = """
MATCH (c:Conversation)
OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
WITH c, count(m) AS messages, max(m.ts) AS last_ts
OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(q:Message {seq: 0})
RETURN c.id, c.user_id, c.started_ts, messages, last_ts, q.text
ORDER BY coalesce(last_ts, c.started_ts) DESC
LIMIT $limit
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:12]}"


def start_conversation(graph: Graph, user_id: str, agent: str = "agent:triage", conversation_id: str | None = None) -> str:
    cid = conversation_id or new_id("conv")
    graph.query(START, {"id": cid, "user": user_id, "ts": now(), "agent": agent})
    return cid


def append_message(graph: Graph, conversation_id: str, role: str, text: str) -> int:
    rows = graph.query(APPEND, {"cid": conversation_id, "mid": new_id("msg"), "role": role, "text": text, "ts": now()}).result_set
    if not rows:
        raise KeyError(f"no conversation {conversation_id}")
    return rows[0][0]


def load_history(graph: Graph, conversation_id: str) -> list[dict]:
    return [{"role": r, "text": t, "seq": s, "ts": ts}
            for r, t, s, ts in graph.ro_query(HISTORY, {"cid": conversation_id}).result_set]


def list_conversations(graph: Graph, limit: int = 20) -> list[dict]:
    return [{"id": i, "user_id": u, "started_ts": st, "messages": n, "last_ts": lt, "title": (q or "")[:80]}
            for i, u, st, n, lt, q in graph.ro_query(LIST, {"limit": limit}).result_set]
