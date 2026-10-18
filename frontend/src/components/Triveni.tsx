"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, Command, IconContext, LayoutGrid, Maximize, MessagesSquare, PanelLeftClose, PanelLeftOpen, Play, Plus, Repeat, Search, Send, CircleCheck, Square, Table2, Wrench, X } from "./icons";
import {
  api, parseEdge, toolAsStep, type AgentResult, type ConversationInfo, type GraphEdge, type GraphNode, type Health,
  type Guard, type Person, type Step, type ToolInfo,
} from "@/lib/api";
import { SCENARIOS, type Scenario } from "@/lib/scenarios";
import { stripEmoji } from "@/lib/text";
import EntryCard, { type Entry } from "./EntryCard";
import GraphCanvas, { edgeKey, type Compare, type LayoutName } from "./GraphCanvas";
import Graph3D from "./Graph3D";
import GraphTable from "./GraphTable";
import RightPanel, { type PanelState, type PanelTab } from "./RightPanel";
import ToolRunner from "./ToolRunner";
import CommandPalette, { type PaletteItem } from "./CommandPalette";
import Splitter from "./Splitter";
import { Chip, ShapeSwatch, TRACK_COLOUR } from "./ui";

/** The rejected-draft record, if the proof check replaced the model's answer (empty object otherwise). */
const guardOf = (r: AgentResult) => (r.guard && "reason" in r.guard ? (r.guard as Guard) : undefined);

// pane widths are a per-viewer convenience: remembered in this browser, never required
const PANES_KEY = "triveni.panes";
const DEFAULT_PANES = { thread: 480, panel: 400, threadOpen: true };
function loadPanes(): typeof DEFAULT_PANES {
  try { return { ...DEFAULT_PANES, ...JSON.parse(localStorage.getItem(PANES_KEY) ?? "{}") }; } catch { return DEFAULT_PANES; }
}

// a sidebar tile: tinted in its section colour, filled when open
const tile = (colour: string, active: boolean) => ({
  color: active ? "var(--on-ink)" : colour,
  background: active ? colour : `color-mix(in srgb, ${colour} 16%, transparent)`,
});

let counter = 0;
const newId = () => `e${++counter}`;
const TREE_TOOLS = new Set(["blast_radius", "decision_trail", "shortest_path"]);

/** Run an async call and measure it (module-level, so it is clearly not part of rendering). */
async function timed<T>(fn: () => Promise<T>): Promise<[T, number]> {
  const t0 = performance.now();
  const value = await fn();
  return [value, Math.round(performance.now() - t0)];
}

/** The node a step was asked about: the centre of tree and radial layouts. */
function rootsOf(steps: Step[]): string[] {
  const roots = new Set<string>();
  for (const s of steps.slice(0, 1)) {
    const i = s.input as Record<string, unknown>;
    if (typeof i.service === "string") roots.add(i.service.includes(":") ? i.service : `svc:${i.service}`);
    for (const k of ["incident", "entity", "person", "source"]) if (typeof i[k] === "string" && String(i[k]).includes(":")) roots.add(String(i[k]));
    if (Array.isArray(i.entities)) i.entities.filter((e) => typeof e === "string" && e.includes(":")).slice(0, 1).forEach((e) => roots.add(e));
  }
  return [...roots];
}

/** Node ids and edge keys of some steps' paths. */
function evidenceOf(steps: Step[]) {
  const edges = new Map<string, GraphEdge>();
  const ids = new Set<string>();
  for (const s of steps) {
    for (const p of s.paths) {
      p.nodes.forEach((n) => ids.add(n));
      for (const ref of p.edges) {
        const e = { ...parseEdge(ref), superseded: p.superseded, stale: p.stale };
        ids.add(e.source); ids.add(e.target);
        edges.set(edgeKey(e), e);
      }
    }
  }
  return { ids, edges };
}

type Flyout = "scenarios" | "conversations" | "tools" | null;
interface GraphState { nodes: GraphNode[]; edges: GraphEdge[]; roots: string[]; title: string; entryId: string | null; spotlight?: Set<string> | null }

export default function Triveni() {
  const [tenants, setTenants] = useState<string[]>([]);
  const [tenant, setTenant] = useState("acme");
  const [health, setHealth] = useState<Health | null>(null);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [focusStep, setFocusStep] = useState<number | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [flyout, setFlyout] = useState<Flyout>(null);
  const [panel, setPanel] = useState<PanelState | null>(null);
  const [coordKey, setCoordKey] = useState(0);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [graph, setGraph] = useState<GraphState>({ nodes: [], edges: [], roots: [], title: "", entryId: null });
  const [layout, setLayout] = useState<LayoutName>("force");
  const [view, setView] = useState<"3d" | "2d" | "table">("3d"); // 3D by default; 2D stays as a flat fallback
  const viewRef = useRef(view);
  useEffect(() => { viewRef.current = view; }, [view]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationInfo[]>([]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [catalog, setCatalog] = useState<GraphNode[]>([]); // services and teams, for node search in the palette
  const [people, setPeople] = useState<Person[]>([]);
  const [toolChoice, setToolChoice] = useState<string | undefined>(undefined);
  const [modKey, setModKey] = useState("Ctrl");
  const [panes, setPanes] = useState(DEFAULT_PANES);
  const [compare, setCompare] = useState<Compare>("both");
  const [overviewData, setOverviewData] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null); // the 3D base
  const composer = useRef<HTMLInputElement>(null);
  const threadEnd = useRef<HTMLDivElement>(null);
  const aborts = useRef(new Map<string, AbortController>());

  const busy = entries.some((e) => e.pending);
  const agentOnline = Boolean(health?.agent);

  // ---------------------------------------------------------------- start-up, tenant data
  useEffect(() => {
    Promise.all([api.health(), api.tenants(), api.tools()])
      .then(([h, t, tl]) => { setHealth(h); setTenants(t); setTools(tl); })
      .catch((e) => setError(`Backend not reachable: ${e.message} · uvicorn backend.app.main:app --reload`));
  }, []);

  const showOverview = useCallback(async (t: string) => {
    try {
      const o = await api.overview(t);
      setGraph({ nodes: o.nodes, edges: o.edges, roots: [], title: "Overview", entryId: null });
      setCatalog(o.nodes);
      setOverviewData(o);
      setLayout("force"); setFocusStep(null); setSelected(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (error) return;
    let live = true; // ignore a late response after the tenant changed
    api.overview(tenant)
      .then((o) => { if (live) { setGraph({ nodes: o.nodes, edges: o.edges, roots: [], title: "Overview", entryId: null }); setCatalog(o.nodes); setOverviewData(o); } })
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [tenant, error]);

  const refreshConversations = useCallback(() => {
    api.conversations(tenant).then(setConversations).catch(() => setConversations([]));
  }, [tenant]);

  useEffect(() => {
    let live = true;
    api.conversations(tenant).then((c) => live && setConversations(c)).catch(() => live && setConversations([]));
    return () => { live = false; };
  }, [tenant]);

  useEffect(() => {
    let live = true;
    api.actions(tenant).then((a) => live && setPendingApprovals(a.filter((x) => x.status === "proposed").length)).catch(() => {});
    return () => { live = false; };
  }, [tenant, coordKey]);

  useEffect(() => {
    let live = true;
    api.people(tenant).then((p) => live && setPeople(p)).catch(() => live && setPeople([]));
    return () => { live = false; };
  }, [tenant]);

  // shortcut label for the search button (read after mount: the server render cannot know the platform)
  useEffect(() => { setModKey(/Mac|iPhone|iPad/.test(navigator.platform) ? "mac" : "Ctrl"); }, []); // eslint-disable-line react-hooks/set-state-in-effect

  useEffect(() => { setPanes(loadPanes()); }, []); // eslint-disable-line react-hooks/set-state-in-effect
  const resize = (patch: Partial<typeof DEFAULT_PANES>) => setPanes((cur) => {
    const next = { ...cur, ...patch };
    try { localStorage.setItem(PANES_KEY, JSON.stringify(next)); } catch { /* storage blocked: widths just are not remembered */ }
    return next;
  });

  useEffect(() => { threadEnd.current?.scrollIntoView({ block: "end" }); }, [entries.length]);

  const switchTenant = (t: string) => {
    setTenant(t);
    setEntries([]); setActiveId(null); setPanel(null); setConversationId(null); setSelected(null); setFocusStep(null);
  };

  // ---------------------------------------------------------------- canvas for a result
  const showResult = useCallback(async (entry: Entry, t: string) => {
    const { ids, edges } = evidenceOf(entry.steps);
    if (!ids.size) return;
    const nodes = await api.nodes(t, [...ids]);
    const first = entry.steps.find((s) => s.paths.length)?.tool ?? "";
    // spotlight = exactly what the tools returned (path nodes and edges), never words from the model's answer
    setGraph({ nodes, edges: [...edges.values()], roots: rootsOf(entry.steps), title: entry.question, entryId: entry.id,
               spotlight: new Set<string>([...ids, ...edges.keys()]) });
    setLayout(TREE_TOOLS.has(first) && viewRef.current === "2d" ? "tree" : "force");
    setFocusStep(null); setSelected(null); setCompare("both");
  }, []);

  const focus = useMemo(() => {
    if (focusStep === null) return null;
    const entry = entries.find((e) => e.id === graph.entryId);
    const step = entry?.steps[focusStep];
    if (!step) return null;
    const { ids, edges } = evidenceOf([step]);
    return new Set<string>([...ids, ...edges.keys()]);
  }, [focusStep, entries, graph.entryId]);

  // 3D shows an answer inside the whole map: overview + the answer's evidence, merged by id
  const graph3d = useMemo(() => {
    if (!graph.spotlight || !overviewData) return graph;
    const nodes = new Map(overviewData.nodes.map((n) => [n.id, n]));
    graph.nodes.forEach((n) => nodes.set(n.id, n));
    const edges = new Map(overviewData.edges.map((e) => [edgeKey(e), e]));
    graph.edges.forEach((e) => edges.set(edgeKey(e), e));
    return { ...graph, nodes: [...nodes.values()], edges: [...edges.values()] };
  }, [graph, overviewData]);

  const update = (id: string, patch: Partial<Entry>) =>
    setEntries((es) => es.map((e) => (e.id === id ? { ...e, ...patch } : e)));

  const add = (entry: Entry) => setEntries((es) => [...es, entry]);

  const finish = async (base: Entry, patch: Partial<Entry>, t: string) => {
    const done = { ...base, ...patch, pending: false };
    update(base.id, { ...patch, pending: false });
    setActiveId(base.id);
    await showResult(done, t);
  };

  // ---------------------------------------------------------------- actions
  const runTool = async (name: string, args: Record<string, unknown>, label: string | undefined, t: string) => {
    const entry: Entry = { id: newId(), question: label ?? name, mode: "tool", pending: true, steps: [], startedAt: Date.now() };
    add(entry);
    try {
      const [r, ms] = await timed(() => api.runTool(t, name, args));
      await finish(entry, { steps: [toolAsStep(name, args, r, ms)], ms, model: "direct" }, t);
    } catch (e) {
      update(entry.id, { pending: false, error: (e as Error).message });
    }
  };

  const ask = async (q: string, t: string) => {
    const entry: Entry = { id: newId(), question: q, mode: "agent", pending: true, steps: [], startedAt: Date.now() };
    add(entry);
    const runId = `run:${crypto.randomUUID().slice(0, 13)}`;
    const ctrl = new AbortController();
    aborts.current.set(entry.id, ctrl);
    const poll = setInterval(() => {
      api.askProgress(runId).then((p) => update(entry.id, { progress: p.events })).catch(() => {});
    }, 700);
    try {
      const [r, ms] = await timed(() => api.ask(t, q, conversationId, runId, ctrl.signal).finally(() => clearInterval(poll)));
      setConversationId(r.conversation_id);
      refreshConversations();
      setCoordKey((k) => k + 1);
      await finish(entry, { answer: r.answer, steps: r.steps, ms, model: r.model, fallbacks: r.fallbacks,
                            conversationId: r.conversation_id, episode: r.episode || undefined, verification: r.verification,
                            guard: guardOf(r) }, t);
    } catch (e) {
      update(entry.id, { pending: false, error: ctrl.signal.aborted ? "Cancelled" : (e as Error).message });
    } finally {
      aborts.current.delete(entry.id);
    }
  };

  const ingest = async (path: string, label: string, t: string) => {
    const entry: Entry = { id: newId(), question: label, mode: "ingest", pending: true, steps: [], startedAt: Date.now() };
    add(entry);
    try {
      const [r, ms] = await timed(() => api.ingest(t, path));
      await finish(entry, { steps: [toolAsStep("ingest_document", { path }, r, ms)], ms, model: "direct" }, t);
      setCoordKey((k) => k + 1); // a changed fact may have proposed a notify_owner action
    } catch (e) {
      update(entry.id, { pending: false, error: (e as Error).message });
    }
  };

  const runScenario = (s: Scenario) => {
    setFlyout(null);
    let t = tenant;
    if (s.tenant && s.tenant !== tenant && tenants.includes(s.tenant)) { switchTenant(s.tenant); t = s.tenant; }
    if (s.ingest) return ingest(s.ingest, s.question, t);
    if (agentOnline) return ask(s.question, t);
    if (s.tool) return runTool(s.tool[0], s.tool[1], s.question, t);
  };

  const addAgentResult = (label: string, r: AgentResult) => {
    const entry: Entry = { id: newId(), question: label, mode: "agent", pending: false, steps: r.steps, answer: r.answer,
                           model: r.model, fallbacks: r.fallbacks, conversationId: r.conversation_id,
                           episode: r.episode || undefined, verification: r.verification, guard: guardOf(r) };
    add(entry);
    setActiveId(entry.id);
    showResult(entry, tenant);
  };

  // Reopen a conversation: its messages come back from the graph (works after a restart)
  const openConversation = async (id: string | null) => {
    setFlyout(null);
    if (!id) { setConversationId(null); setEntries([]); return; }
    try {
      const c = await api.conversation(tenant, id);
      const restored: Entry[] = [];
      for (let i = 0; i < c.messages.length; i += 2) {
        const q = c.messages[i], a = c.messages[i + 1];
        restored.push({ id: newId(), question: q.text, mode: "agent", pending: false, steps: [], answer: a?.text,
                        conversationId: id, restored: true });
      }
      setEntries(restored);
      setConversationId(id);
      setActiveId(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // Grow the canvas from any node: its current neighbours (depth 1 or 2) are merged into what is shown
  const expandNode = async (id: string, depth: 1 | 2 = 1) => {
    try {
      const r = await api.expand(tenant, id, depth);
      setGraph((g) => {
        const nodes = new Map(g.nodes.map((n) => [n.id, n]));
        r.nodes.forEach((n) => { if (!nodes.has(n.id)) nodes.set(n.id, n); });
        const edges = new Map(g.edges.map((e) => [edgeKey(e), e]));
        r.edges.forEach((e) => { if (!edges.has(edgeKey(e))) edges.set(edgeKey(e), e); });
        return { ...g, nodes: [...nodes.values()], edges: [...edges.values()] };
      });
      setSelected(id);
      setFocusStep(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // ---------------------------------------------------------------- right panel
  const openId = (id: string) => {
    if (id.startsWith("doc:")) { setPanel({ ...(panel ?? {}), tab: "source", docId: id }); return; }
    setSelected(id);
    setPanel({ ...(panel ?? {}), tab: "node", nodeId: id });
  };
  const openCypher = (step: Step) => setPanel({ ...(panel ?? {}), tab: "cypher", step });
  const openApprovals = () => setPanel({ ...(panel ?? {}), tab: "approvals" });
  const selectNode = (id: string | null) => {
    setSelected(id);
    if (id) setPanel((p) => ({ ...(p ?? {}), tab: "node", nodeId: id }));
  };

  // ---------------------------------------------------------------- keyboard
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest("input, textarea, select");
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setPaletteOpen((o) => !o); return; }
      if (paletteOpen) return; // the palette handles its own keys
      if (e.key === "Escape") { if (flyout) setFlyout(null); else setPanel(null); return; }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") { e.preventDefault(); composer.current?.focus(); return; }
      if (!entries.length && !busy && /^[1-9]$/.test(e.key)) {
        const s = SCENARIOS.find((x) => x.n === Number(e.key));
        if (s) runScenario(s);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const openTool = (name?: string) => { setToolChoice(name); setFlyout("tools"); };

  const paletteItems = (): PaletteItem[] => {
    const nodes = new Map<string, { id: string; name: string; label: string }>();
    [...graph.nodes, ...catalog].forEach((n) => nodes.set(n.id, n));
    people.forEach((p) => nodes.set(p.id, { id: p.id, name: p.name, label: "Person" }));
    const shown = new Set(graph.nodes.map((n) => n.id));
    return [
      ...SCENARIOS.map((sc) => ({ id: `scenario:${sc.n}`, group: "Scenarios", label: sc.label, hint: `#${sc.n}`,
                                 keywords: sc.question, icon: <Play size={14} />, run: () => { runScenario(sc); } })),
      { id: "action:overview", group: "Actions", label: "Overview", icon: <LayoutGrid size={14} />, run: () => { showOverview(tenant); } },
      { id: "action:3d", group: "Actions", label: "3D view", icon: <Box size={14} />, run: () => setView("3d") },
      { id: "action:2d", group: "Actions", label: "2D view", icon: <Square size={14} />, run: () => setView("2d") },
      { id: "action:table", group: "Actions", label: "Table view", icon: <Table2 size={14} />, run: () => setView("table") },
      { id: "action:approvals", group: "Actions", label: "Approvals", hint: pendingApprovals ? String(pendingApprovals) : undefined,
        icon: <CircleCheck size={14} />, run: openApprovals },
      { id: "action:new", group: "Actions", label: "New conversation", icon: <Plus size={14} />, run: () => { openConversation(null); } },
      { id: "action:fit", group: "Actions", label: "Fit graph", hint: "f", icon: <Maximize size={14} />,
        run: () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "f" })) },
      ...conversations.map((c) => ({ id: `conv:${c.id}`, group: "Conversations", label: stripEmoji(c.title), hint: c.id,
                                     icon: <MessagesSquare size={14} />, run: () => { openConversation(c.id); } })),
      ...tools.filter((t) => t.read_only).map((t) => ({ id: `tool:${t.name}`, group: "Tools", label: t.name, keywords: t.description,
                                                       icon: <Wrench size={14} />, run: () => openTool(t.name) })),
      ...[...nodes.values()].map((n) => ({ id: `node:${n.id}`, group: "Nodes", label: n.name, hint: n.id, keywords: n.label,
                                           icon: <ShapeSwatch label={n.label} />,
                                           run: () => (shown.has(n.id) ? selectNode(n.id) : openId(n.id)) })),
    ];
  };

  const submit = () => {
    const q = question.trim();
    if (!q || busy) return;
    setQuestion("");
    ask(q, tenant);
  };

  // ---------------------------------------------------------------- layout
  // the demo scenarios as one list, in order; the number is the shortcut, coloured by its first track
  const scenarioGrid = (compact: boolean) => (
    <div className={compact ? "space-y-3" : "space-y-5 px-5 py-6"}>
      <section>
          <h3 className="mb-1.5 text-[13px] font-semibold text-ink">Try these</h3>
          <ul>
            {[...SCENARIOS].sort((a, b) => a.n - b.n).map((s) => { const col = { track: s.tracks[0] }; return (
              <li key={s.n}>
                <button disabled={busy} onClick={() => runScenario(s)}
                        className="flex w-full items-center gap-3 rounded-lg px-1.5 py-1.5 text-left text-[14px] text-ink-2 hover:bg-raised hover:text-ink disabled:opacity-50">
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md font-mono text-[11px] font-medium"
                        style={{ color: TRACK_COLOUR[col.track], background: `color-mix(in srgb, ${TRACK_COLOUR[col.track]} 16%, transparent)` }}>{s.n}</span>
                  <span>{s.label}</span>
                </button>
              </li>
            ); })}
          </ul>
      </section>
    </div>
  );

  return (
    <IconContext.Provider value={{ weight: "duotone" }}>
    <div className="flex h-screen flex-col bg-bg text-ink">
      {/* top bar */}
      <header className="flex h-12 shrink-0 items-center gap-3 bg-bg px-4">
        <span className="text-[15px] font-bold tracking-tight">Triveni</span>
        <span className="h-5 w-px bg-line" aria-hidden />
        <label className="flex items-center gap-1.5 text-xs text-ink-3">
          <select value={tenant} onChange={(e) => switchTenant(e.target.value)} aria-label="Tenant"
                  className="rounded border border-line bg-panel px-2 py-1 text-[13px] font-medium text-ink">
            {(tenants.length ? tenants : [tenant]).map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <button onClick={() => setPaletteOpen(true)}
                className="ml-4 flex w-64 items-center gap-2 rounded border border-line bg-raised px-2.5 py-1 text-[13px] text-ink-3 hover:border-line-strong">
          <Search size={14} aria-hidden /><span className="flex-1 text-left">Search</span>
          <kbd className="inline-flex items-center gap-0.5 rounded border border-line bg-panel px-1 font-mono text-[11px]">
            {modKey === "mac" ? <Command size={11} aria-label="Command" /> : modKey} K
          </kbd>
        </button>
        <div className="ml-auto flex items-center gap-2 text-xs">
          {health?.demo_replay && <Chip tone="warn"><Repeat size={12} aria-hidden />Replay</Chip>}
        </div>
      </header>

      {error && (
        <div className="flex items-center gap-2 bg-bad-soft px-4 py-1.5 font-mono text-xs text-bad">
          <span className="flex-1">{error}</span>
          <button onClick={() => setError(null)} aria-label="Dismiss"><X size={14} /></button>
        </div>
      )}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} items={paletteOpen ? paletteItems() : []} />

      <main className="flex min-h-0 flex-1 gap-1 px-2 pb-2">
        {/* icon sidebar */}
        <nav aria-label="Sidebar" className="mr-1 flex w-12 shrink-0 flex-col items-center gap-1 rounded-xl border border-line bg-panel py-2">
          {([
            ["scenarios", "Scenarios", LayoutGrid, "var(--c-fuchsia)"],
            ["conversations", "Conversations", MessagesSquare, "var(--c-teal)"],
            ["tools", "Tools", Wrench, "var(--c-yellow)"],
          ] as const).map(([key, label, Icon, colour]) => (
            <button key={key} title={label} aria-label={label} aria-pressed={flyout === key} onClick={() => setFlyout(flyout === key ? null : key)}
                    style={tile(colour, flyout === key)} className="grid h-9 w-9 place-items-center rounded-lg hover:brightness-125">
              <Icon size={19} />
            </button>
          ))}
          <button title="Approvals" aria-label="Approvals" onClick={openApprovals}
                  style={tile("var(--c-green)", panel?.tab === "approvals")} className="relative grid h-9 w-9 place-items-center rounded-lg hover:brightness-125">
            <CircleCheck size={19} />
            {pendingApprovals > 0 && (
              <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-[2px] bg-warn px-0.5 text-center font-mono text-[10px] leading-4 text-on-ink">{pendingApprovals}</span>
            )}
          </button>
          <button title={panes.threadOpen ? "Hide thread" : "Show thread"} aria-label={panes.threadOpen ? "Hide thread" : "Show thread"}
                  aria-pressed={!panes.threadOpen} onClick={() => resize({ threadOpen: !panes.threadOpen })}
                  className="mt-auto grid h-9 w-9 place-items-center rounded-lg bg-raised text-ink-2 hover:bg-line-strong hover:text-ink">
            {panes.threadOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
          </button>
        </nav>

        {/* thread */}
        <section style={{ width: panes.thread }} className={`relative shrink-0 flex-col overflow-hidden rounded-xl border border-line bg-panel ${panes.threadOpen ? "flex" : "hidden"}`}>
          {flyout && <div className="absolute inset-0 z-20 bg-ink/20" onClick={() => setFlyout(null)} aria-hidden />}
          {flyout && (
            <div className="absolute inset-x-0 top-0 z-30 max-h-[75%] overflow-auto border-b border-line bg-panel p-3">
              <div className="mb-2 flex items-center">
                <h2 className="text-[13px] font-semibold capitalize text-ink">{flyout}</h2>
                <button onClick={() => setFlyout(null)} aria-label="Close" className="ml-auto rounded p-1 text-ink-3 hover:bg-raised"><X size={14} /></button>
              </div>
              {flyout === "scenarios" && scenarioGrid(true)}
              {flyout === "tools" && <ToolRunner key={toolChoice ?? "default"} initial={toolChoice} tools={tools} busy={busy}
                                              onRun={(n, a) => { setFlyout(null); runTool(n, a, undefined, tenant); }} />}
              {flyout === "conversations" && (
                <div className="space-y-1">
                  <button onClick={() => openConversation(null)}
                          className="flex w-full items-center gap-1.5 rounded border border-dashed border-line-strong px-2.5 py-2 text-[13px] font-medium text-ink-2 hover:bg-raised">
                    <Plus size={14} />New
                  </button>
                  {conversations.map((c) => (
                    <button key={c.id} onClick={() => openConversation(c.id)}
                            className={`flex w-full items-center gap-2 rounded px-2.5 py-2 text-left hover:bg-raised ${c.id === conversationId ? "bg-accent-soft" : ""}`}>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] text-ink">{stripEmoji(c.title)}</span>
                        <span className="font-mono text-[11px] text-ink-3">{c.id} · {(c.last_ts ?? c.started_ts).slice(0, 16).replace("T", " ")}</span>
                      </span>
                      <span className="text-xs tabular-nums text-ink-3">{c.messages}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="relative z-0 flex-1 overflow-auto">
            {entries.length === 0 ? scenarioGrid(false) : entries.map((e) => (
              <EntryCard key={e.id} entry={e} tenant={tenant} active={e.id === activeId}
                         focusStep={graph.entryId === e.id ? focusStep : null}
                         onSelect={() => { setActiveId(e.id); showResult(e, tenant); }}
                         onOpen={openId} onHover={setHover} onCypher={openCypher} onApprovals={openApprovals}
                         onStep={(i) => {
                           if (graph.entryId !== e.id) { setActiveId(e.id); showResult(e, tenant).then(() => setFocusStep(i)); }
                           else setFocusStep(i);
                         }}
                         onCancel={() => aborts.current.get(e.id)?.abort()} />
            ))}
            <div ref={threadEnd} />
          </div>

          <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="border-t border-line bg-panel p-3">
            <div className="flex items-center gap-2 rounded border border-line-strong bg-panel px-3 py-2 focus-within:border-accent">
              <input ref={composer} value={question} onChange={(e) => setQuestion(e.target.value)} disabled={!agentOnline}
                     placeholder={agentOnline ? "Ask" : "Agent offline"} aria-label="Question"
                     className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3 disabled:opacity-60" />
              {conversationId && <span className="font-mono text-[11px] text-ink-3">{conversationId}</span>}
              <button disabled={!agentOnline || busy || !question.trim()} aria-label="Send"
                      className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-on-accent hover:brightness-110 disabled:opacity-40"><Send size={14} /></button>
            </div>
          </form>
        </section>

        {panes.threadOpen && (
          <Splitter label="Resize thread" value={panes.thread} min={340} max={760} reset={DEFAULT_PANES.thread} grow="right"
                    onChange={(w) => resize({ thread: w })} />
        )}

        {/* graph */}
        <section className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-panel">
          <div className="flex h-10 shrink-0 items-center gap-3 border-b border-line px-3 text-xs">
            <div role="tablist" className="flex gap-0.5 rounded-lg bg-raised p-0.5">
              {([["3d", "3D"], ["2d", "2D"], ["table", "Table"]] as const).map(([v, label]) => (
                <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}
                        className="tab">{label}</button>
              ))}
            </div>
            <span className="min-w-0 flex-1 truncate font-medium text-ink-2" title={graph.title}>{graph.title}</span>
            <span className="tabular-nums text-ink-3">{graph.nodes.length} nodes · {graph.edges.length} edges</span>
            {graph.edges.some((e) => e.superseded) && (
              <div role="radiogroup" aria-label="Before or after the change" className="flex gap-0.5 rounded-lg bg-raised p-0.5">
                {(["before", "after", "both"] as const).map((m) => (
                  <button key={m} role="radio" aria-checked={compare === m} onClick={() => setCompare(m)}
                          className="tab capitalize">{m}</button>
                ))}
              </div>
            )}
            {focusStep !== null && <Chip tone="info">step {focusStep + 1}<button onClick={() => setFocusStep(null)} aria-label="Clear step"><X size={11} /></button></Chip>}
            {graph.entryId && (
              <button onClick={() => showOverview(tenant)} className="btn btn-sm">Overview</button>
            )}
          </div>
          <div className="relative isolate min-h-0 flex-1">
            {view === "3d" && (
              <Graph3D nodes={graph3d.nodes} edges={graph3d.edges} roots={graph.roots} focus={focus} hover={hover} spotlight={graph.spotlight}
                       layout={layout} onLayout={setLayout} selected={selected} onSelect={selectNode}
                       onExpand={(id) => expandNode(id, 1)} compare={compare}
                       onUnavailable={() => { setView("2d"); setError("3D needs WebGL, which this browser has turned off: showing 2D"); }} />
            )}
            <div className={view === "2d" ? "h-full" : "hidden"}>
              <GraphCanvas nodes={graph.nodes} edges={graph.edges} roots={graph.roots} focus={focus} hover={hover}
                           layout={layout} onLayout={setLayout} selected={selected} onSelect={selectNode}
                           onExpand={(id) => expandNode(id, 1)} compare={compare} />
            </div>
            {view === "table" && <GraphTable nodes={graph.nodes} edges={graph.edges} onOpen={openId} />}
          </div>
        </section>

        {panel && (
          <Splitter label="Resize panel" value={panes.panel} min={320} max={720} reset={DEFAULT_PANES.panel} grow="left"
                    onChange={(w) => resize({ panel: w })} />
        )}
        {panel && (
          <RightPanel width={panes.panel} state={panel} tenant={tenant} refreshKey={coordKey}
                      onTab={(t: PanelTab) => setPanel({ ...panel, tab: t })} onClose={() => setPanel(null)} onOpen={openId}
                      onResult={addAgentResult} onChanged={() => setCoordKey((k) => k + 1)} onExpand={expandNode} />
        )}
      </main>
    </div>
    </IconContext.Provider>
  );
}
