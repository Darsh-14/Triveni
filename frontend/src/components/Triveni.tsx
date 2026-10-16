"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, parseEdge, toolAsStep, type ConversationInfo, type GraphEdge, type GraphNode, type Health, type Step, type ToolInfo } from "@/lib/api";
import Drawer, { type DrawerContent } from "./Drawer";
import EntryCard, { type Entry } from "./EntryCard";
import GraphCanvas, { edgeKey, LABEL_COLOURS } from "./GraphCanvas";
import Coordination from "./Coordination";
import ToolRunner from "./ToolRunner";

// Demo scenarios (MVP.md Section 5). With the agent online the question goes to Claude over MCP;
// otherwise the scenario's main tool runs directly, so the demo still works without a model.
const SCENARIOS: { n: number; label: string; question: string; tool?: [string, Record<string, unknown>]; ingest?: string }[] = [
  { n: 1, label: "payments-api is failing", question: "payments-api is failing, what's affected and who do I page?",
    tool: ["blast_radius", { service: "payments-api" }] },
  { n: 2, label: "Change retry policy on orders-api?", question: "Can we change the retry policy on orders-api?",
    tool: ["decision_trail", { service: "orders-api", action: "change_retry_policy" }] },
  { n: 3, label: "Who is on call for billing-batch?", question: "Who is on call for billing-batch?",
    tool: ["why_not", { kind: "on_call", service: "billing-batch" }] },
  { n: 4, label: "Single points of knowledge?", question: "Which engineers are single points of knowledge?",
    tool: ["key_people", {}] },
  { n: 6, label: "Hand off inc:0057 to remediation", question: "inc:0057: orders-api p99 latency is above 4s and workers are saturated. Investigate briefly, then hand it off to remediation for a fix.",
    tool: ["similar_incidents", { incident: "inc:0057" }] },
  { n: 7, label: "Ingest: billing-batch moves to Atlas", question: "Ingest #eng-announcements: billing-batch moves to Team Atlas",
    ingest: "data/raw/live/chat-billing-move.md" },
];

let counter = 0;
const newId = () => `e${++counter}`;

/** Run an async call and measure it (module-level, so it is clearly not part of rendering). */
async function timed<T>(fn: () => Promise<T>): Promise<[T, number]> {
  const t0 = performance.now();
  const value = await fn();
  return [value, Math.round(performance.now() - t0)];
}

export default function Triveni() {
  const [tenants, setTenants] = useState<string[]>([]);
  const [tenant, setTenant] = useState("acme");
  const [health, setHealth] = useState<Health | null>(null);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [panel, setPanel] = useState<"ask" | "tool" | "coord">("ask");
  const [coordKey, setCoordKey] = useState(0);
  const [drawer, setDrawer] = useState<DrawerContent | null>(null);
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[]; highlight: Set<string>; title: string }>(
    { nodes: [], edges: [], highlight: new Set(), title: "" });
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationInfo[]>([]);

  const busy = entries.some((e) => e.pending);
  const agentOnline = Boolean(health?.agent);

  // ---------------------------------------------------------------- start-up and tenant switch
  useEffect(() => {
    Promise.all([api.health(), api.tenants(), api.tools()])
      .then(([h, t, tl]) => { setHealth(h); setTenants(t); setTools(tl); })
      .catch((e) => setError(`Backend not reachable: ${e.message}. Start it with: uvicorn backend.app.main:app --reload`));
  }, []);

  const showOverview = useCallback(async (t: string) => {
    try {
      const o = await api.overview(t);
      setGraph({ nodes: o.nodes, edges: o.edges, highlight: new Set(), title: `${t}: services and owning teams` });
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (error) return;
    let live = true; // ignore a late response after the tenant changed
    api.overview(tenant)
      .then((o) => live && setGraph({ nodes: o.nodes, edges: o.edges, highlight: new Set(), title: `${tenant}: services and owning teams` }))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [tenant, error]);

  const switchTenant = (t: string) => {
    setTenant(t);
    setEntries([]);
    setActiveId(null);
    setDrawer(null);
    setConversationId(null);
  };

  const refreshConversations = useCallback(() => {
    api.conversations(tenant).then(setConversations).catch(() => setConversations([]));
  }, [tenant]);

  useEffect(() => {
    let live = true;
    api.conversations(tenant).then((c) => live && setConversations(c)).catch(() => live && setConversations([]));
    return () => { live = false; };
  }, [tenant]);

  // Reopen a conversation: its messages come back from the graph (works after a restart)
  const openConversation = async (id: string) => {
    if (!id) { setConversationId(null); setEntries([]); return; }
    try {
      const c = await api.conversation(tenant, id);
      const restored: Entry[] = [];
      for (let i = 0; i < c.messages.length; i += 2) {
        const q = c.messages[i], a = c.messages[i + 1];
        restored.unshift({ id: newId(), question: q.text, mode: "agent", pending: false, steps: [], answer: a?.text,
                           memory: `restored from ${id} (message ${q.seq})` });
      }
      setEntries(restored);
      setConversationId(id);
      setActiveId(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // ---------------------------------------------------------------- canvas for a result
  const showResult = useCallback(async (entry: Entry) => {
    const edges = new Map<string, GraphEdge>();
    const ids = new Set<string>();
    for (const s of entry.steps) {
      for (const p of s.paths) {
        p.nodes.forEach((n) => ids.add(n));
        for (const ref of p.edges) {
          const e = { ...parseEdge(ref), superseded: p.superseded, stale: p.stale };
          ids.add(e.source); ids.add(e.target);
          edges.set(edgeKey(e), e);
        }
      }
    }
    if (!ids.size) return;
    const nodes = await api.nodes(tenant, [...ids]);
    const highlight = new Set<string>([...ids, ...edges.keys()]);
    setGraph({ nodes, edges: [...edges.values()], highlight, title: `Evidence for: ${entry.question}` });
  }, [tenant]);

  const update = (id: string, patch: Partial<Entry>) =>
    setEntries((es) => es.map((e) => (e.id === id ? { ...e, ...patch } : e)));

  const finish = async (id: string, patch: Partial<Entry>, base: Entry) => {
    const done = { ...base, ...patch, pending: false };
    update(id, { ...patch, pending: false });
    setActiveId(id);
    await showResult(done);
  };

  // ---------------------------------------------------------------- actions
  const runTool = async (name: string, args: Record<string, unknown>, label?: string) => {
    const entry: Entry = { id: newId(), question: label ?? `${name}(${JSON.stringify(args)})`, mode: "tool", pending: true, steps: [] };
    setEntries((es) => [entry, ...es]);
    try {
      const [r, ms] = await timed(() => api.runTool(tenant, name, args));
      await finish(entry.id, { steps: [toolAsStep(name, args, r, ms)], data: r.data }, entry);
    } catch (e) {
      update(entry.id, { pending: false, error: (e as Error).message });
    }
  };

  const ask = async (q: string) => {
    const entry: Entry = { id: newId(), question: q, mode: "agent", pending: true, steps: [] };
    setEntries((es) => [entry, ...es]);
    try {
      const r = await api.ask(tenant, q, conversationId);
      setConversationId(r.conversation_id);
      refreshConversations();
      setCoordKey((k) => k + 1);
      await finish(entry.id, { answer: r.answer, steps: r.steps, memory: `${r.conversation_id} · ${r.episode || "no episode"}`,
                              model: r.fallbacks.length ? `${r.model} (fell back: ${r.fallbacks.map((f) => f.split(":")[0]).join(", ")})` : r.model }, entry);
    } catch (e) {
      update(entry.id, { pending: false, error: (e as Error).message });
    }
  };

  const ingest = async (path: string, label: string) => {
    const entry: Entry = { id: newId(), question: label, mode: "ingest", pending: true, steps: [] };
    setEntries((es) => [entry, ...es]);
    try {
      const [r, ms] = await timed(() => api.ingest(tenant, path));
      await finish(entry.id, { steps: [toolAsStep("ingest_document", { path }, r, ms)], data: r.data }, entry);
    } catch (e) {
      update(entry.id, { pending: false, error: (e as Error).message });
    }
  };

  const runScenario = (s: (typeof SCENARIOS)[number]) => {
    if (s.ingest) return ingest(s.ingest, s.question);
    if (agentOnline) return ask(s.question);
    if (s.tool) return runTool(s.tool[0], s.tool[1], s.question);
  };

  const openDoc = async (id: string) => {
    setDrawer({ kind: "doc", id, doc: null });
    try {
      setDrawer({ kind: "doc", id, doc: await api.document(tenant, id) });
    } catch (e) {
      setDrawer({ kind: "doc", id, doc: null, error: (e as Error).message });
    }
  };

  const openCypher = (step: Step) => setDrawer({ kind: "cypher", step });
  const legend = useMemo(() => [...new Set(graph.nodes.map((n) => n.label))], [graph.nodes]);

  // ---------------------------------------------------------------- layout
  return (
    <div className="flex h-screen flex-col bg-gray-50 text-gray-900">
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-5 py-2.5">
        <div className="flex items-baseline gap-3">
          <h1 className="text-lg font-bold tracking-tight">Triveni</h1>
          <span className="text-xs text-gray-500">engineering Company Brain on FalkorDB · every answer proves its path</span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className={health?.falkordb ? "text-green-700" : "text-red-700"}>● FalkorDB</span>
          <span className={health?.model_backed ? "text-green-700" : "text-amber-600"}
                title="Providers are tried in order; rules = keyword planner, no model (set GROQ_API_KEY / GEMINI_API_KEY)">
            ● Agent {health ? health.providers.join(" → ") : "…"}
          </span>
          <label className="flex items-center gap-1">
            tenant
            <select value={tenant} onChange={(e) => switchTenant(e.target.value)}
                    className="rounded border border-gray-300 bg-white px-1.5 py-0.5">
              {(tenants.length ? tenants : [tenant]).map((t) => <option key={t}>{t}</option>)}
            </select>
          </label>
        </div>
      </header>

      {error && <div className="bg-red-50 px-5 py-2 text-sm text-red-800">{error}</div>}

      <main className="flex min-h-0 flex-1">
        {/* left: scenarios, input, conversation */}
        <section className="flex w-[460px] min-w-[400px] flex-col border-r border-gray-200 bg-gray-50">
          <div className="space-y-2 border-b border-gray-200 bg-white p-3">
            <div className="flex flex-wrap gap-1.5">
              {SCENARIOS.map((s) => (
                <button key={s.n} disabled={busy} onClick={() => runScenario(s)}
                        className="rounded-full border border-gray-300 px-2.5 py-1 text-xs hover:bg-gray-100 disabled:opacity-50">
                  <span className="font-semibold text-gray-500">#{s.n}</span> {s.label}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-gray-500">conversation</span>
              <select value={conversationId ?? ""} onChange={(e) => openConversation(e.target.value)}
                      className="min-w-0 flex-1 rounded border border-gray-300 bg-white px-1.5 py-0.5">
                <option value="">new conversation</option>
                {conversations.map((c) => (
                  <option key={c.id} value={c.id}>{c.id} · {c.messages} msgs · {c.title}</option>
                ))}
              </select>
            </div>
            <div className="flex gap-1 text-xs">
              {(["ask", "tool", "coord"] as const).map((p) => (
                <button key={p} onClick={() => setPanel(p)}
                        className={`rounded px-2 py-0.5 ${panel === p ? "bg-gray-900 text-white" : "text-gray-600 hover:bg-gray-100"}`}>
                  {p === "ask" ? "Ask the agent" : p === "tool" ? "Run a tool" : "Handoffs & approvals"}
                </button>
              ))}
            </div>
            {panel === "ask" ? (
              <form onSubmit={(e) => { e.preventDefault(); if (question.trim()) { ask(question.trim()); setQuestion(""); } }}
                    className="flex gap-2">
                <input value={question} onChange={(e) => setQuestion(e.target.value)} disabled={!agentOnline}
                       placeholder={agentOnline ? "Ask about services, owners, incidents, decisions…" : "Agent offline: use the scenarios or Run a tool"}
                       className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-sm disabled:bg-gray-100" />
                <button disabled={!agentOnline || busy}
                        className="rounded bg-gray-900 px-3 text-sm font-medium text-white disabled:opacity-50">Ask</button>
              </form>
            ) : panel === "tool" ? (
              <ToolRunner tools={tools} busy={busy} onRun={(n, a) => runTool(n, a)} />
            ) : (
              <Coordination tenant={tenant} refreshKey={coordKey} onResult={(label, r) => {
                if (!r.result) return;
                const res = r.result;
                const entry: Entry = { id: newId(), question: label, mode: "agent", pending: false, steps: res.steps, answer: res.answer,
                                       model: res.model, memory: `${res.conversation_id} · ${res.episode || "no episode"}` };
                setEntries((es) => [entry, ...es]);
                setActiveId(entry.id);
                showResult(entry);
              }} />
            )}
          </div>
          <div className="flex-1 space-y-2 overflow-auto p-3">
            {entries.length === 0 && (
              <p className="pt-6 text-center text-sm text-gray-400">
                Pick a scenario above. Each answer shows the tools used, the Cypher they ran, the path on the graph, and its sources.
              </p>
            )}
            {entries.map((e) => (
              <EntryCard key={e.id} entry={e} active={e.id === activeId}
                         onSelect={() => { setActiveId(e.id); showResult(e); }} onCypher={openCypher} onDoc={openDoc} />
            ))}
          </div>
        </section>

        {/* centre: graph canvas */}
        <section className="relative flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-1.5 text-xs">
            <span className="truncate text-gray-600">{graph.title}</span>
            <div className="flex items-center gap-3">
              {legend.map((l) => (
                <span key={l} className="flex items-center gap-1 text-gray-600">
                  <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: LABEL_COLOURS[l] }} />{l}
                </span>
              ))}
              <button onClick={() => showOverview(tenant)} className="rounded border border-gray-300 px-2 py-0.5 hover:bg-gray-100">
                Overview
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1">
            <GraphCanvas nodes={graph.nodes} edges={graph.edges} highlight={graph.highlight} />
          </div>
          {drawer && <Drawer content={drawer} onClose={() => setDrawer(null)} onDoc={openDoc} />}
        </section>
      </main>
    </div>
  );
}
