"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Copy, X } from "lucide-react";
import { api, type Doc, type NodeDetail, type Step } from "@/lib/api";
import { ID_PATTERN } from "@/lib/entities";
import type { AgentResult } from "@/lib/api";
import Approvals from "./Coordination";
import { DocIcon, EntityChip, ShapeSwatch, TrackTags } from "./ui";

export type PanelTab = "node" | "cypher" | "source" | "approvals";
export interface PanelState { tab: PanelTab; nodeId?: string; step?: Step; docId?: string }

// ------------------------------------------------------------------ Cypher keyword highlighting (no dependency)
const KEYWORDS = /\b(MATCH|OPTIONAL|WHERE|RETURN|WITH|ORDER BY|ORDER|BY|LIMIT|SKIP|UNWIND|MERGE|CREATE|SET|DELETE|DETACH|CALL|YIELD|AS|AND|OR|NOT|IN|IS|NULL|DISTINCT|CASE|WHEN|THEN|ELSE|END|ON|COLLECT|COUNT|EXISTS|DESC|ASC|UNION|ALL)\b/g;

function Cypher({ text }: { text: string }) {
  const out: ReactNode[] = [];
  const token = /(\$\w+)|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|(\/\/.*$)|(:[A-Z_][A-Z_0-9]*\b|:[A-Z][A-Za-z]*\b)/gm;
  let last = 0;
  const pushPlain = (s: string, key: string) => {
    let i = 0;
    for (const m of s.matchAll(KEYWORDS)) {
      out.push(s.slice(i, m.index));
      out.push(<span key={`${key}-${m.index}`} className="font-semibold text-[#93c5fd]">{m[0]}</span>);
      i = (m.index ?? 0) + m[0].length;
    }
    out.push(s.slice(i));
  };
  for (const m of text.matchAll(token)) {
    pushPlain(text.slice(last, m.index), `p${last}`);
    const cls = m[1] ? "text-[#fbbf24]" : m[2] ? "text-[#86efac]" : m[3] ? "text-[#94a3b8] italic" : "text-[#f9a8d4]";
    out.push(<span key={`t${m.index}`} className={cls}>{m[0]}</span>);
    last = (m.index ?? 0) + m[0].length;
  }
  pushPlain(text.slice(last), "end");
  return <pre className="overflow-auto whitespace-pre rounded-md bg-[#0f172a] p-3 font-mono text-[12px] leading-relaxed text-[#e2e8f0]">{out}</pre>;
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button onClick={() => { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200); }}
            className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-xs text-ink-2 hover:bg-raised">
      <Copy size={12} />{done ? "Copied" : "Copy"}
    </button>
  );
}

// ------------------------------------------------------------------ tabs
function NodeTab({ tenant, id, onOpen }: { tenant: string; id: string; onOpen: (id: string) => void }) {
  const [node, setNode] = useState<{ id: string; data: NodeDetail | null; error?: string } | null>(null);
  useEffect(() => {
    let live = true;
    api.node(tenant, id).then((d) => live && setNode({ id, data: d }))
      .catch((e) => live && setNode({ id, data: null, error: (e as Error).message }));
    return () => { live = false; };
  }, [tenant, id]);
  if (!node || node.id !== id) return <p className="animate-pulse text-xs text-ink-3">{id}</p>;
  if (!node.data) return <p className="text-xs text-bad">{node.error}</p>;
  const n = node.data;
  const current = n.edges.filter((e) => !e.valid_to);
  const past = n.edges.filter((e) => e.valid_to);
  const props = Object.entries(n.properties).filter(([k]) => k !== "id");
  const edgeRows = (list: typeof n.edges, old = false) => list.map((e, i) => (
    <tr key={i} className="border-t border-line">
      <td className="whitespace-nowrap py-1 pr-2 font-mono text-[11px] text-ink-3">{e.out ? "→" : "←"} <span className={old ? "line-through" : ""}>{e.type}</span></td>
      <td className="w-full max-w-0 py-1"><EntityChip id={e.id} name={e.name} struck={old} onOpen={onOpen} /></td>
      <td className="max-w-28 py-1 pl-2 text-right">{e.source_doc && <EntityChip id={e.source_doc} onOpen={onOpen} />}</td>
    </tr>
  ));
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <ShapeSwatch label={n.label} size={16} />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{String(n.properties.name ?? n.properties.title ?? n.id)}</p>
          <p className="flex items-center gap-1 font-mono text-[11px] text-ink-3">{n.label} · {n.id} <CopyButton text={n.id} /></p>
        </div>
      </div>
      <table className="w-full text-xs">
        <tbody>
          {props.map(([k, v]) => (
            <tr key={k} className="border-t border-line align-top">
              <td className="w-28 py-1 pr-2 font-mono text-[11px] text-ink-3">{k}</td>
              <td className="break-words py-1 text-ink-2">{Array.isArray(v) ? v.join(", ") : String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div>
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Current · {current.length}</p>
        <table className="w-full text-xs"><tbody>{edgeRows(current)}</tbody></table>
      </div>
      {past.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-3">History · {past.length}</p>
          <table className="w-full text-xs"><tbody>{edgeRows(past, true)}</tbody></table>
        </div>
      )}
    </div>
  );
}

function CypherTab({ step }: { step: Step }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm font-semibold text-ink">{step.tool}</span>
        <TrackTags tracks={step.tracks} />
        <span className="ml-auto"><CopyButton text={step.cypher} /></span>
      </div>
      <Cypher text={step.cypher} />
      <table className="w-full text-xs">
        <tbody>
          {Object.entries(step.params).map(([k, v]) => (
            <tr key={k} className="border-t border-line">
              <td className="w-28 py-1 pr-2 font-mono text-[11px] text-[#b45309]">${k}</td>
              <td className="break-all py-1 font-mono text-[11px] text-ink-2">{JSON.stringify(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SourceTab({ tenant, id, onOpen }: { tenant: string; id: string; onOpen: (id: string) => void }) {
  const [doc, setDoc] = useState<{ id: string; data: Doc | null; error?: string } | null>(null);
  useEffect(() => {
    let live = true;
    api.document(tenant, id).then((d) => live && setDoc({ id, data: d }))
      .catch((e) => live && setDoc({ id, data: null, error: (e as Error).message }));
    return () => { live = false; };
  }, [tenant, id]);
  if (!doc || doc.id !== id) return <p className="animate-pulse text-xs text-ink-3">{id}</p>;
  if (!doc.data) return <p className="text-xs text-bad">{doc.error}</p>;
  const d = doc.data;
  // ids inside the text open in the Node tab
  const body: ReactNode[] = [];
  let last = 0;
  for (const m of d.text.matchAll(ID_PATTERN)) {
    body.push(d.text.slice(last, m.index));
    body.push(<button key={m.index} onClick={() => onOpen(m[0])} className="font-mono text-accent underline decoration-dotted">{m[0]}</button>);
    last = (m.index ?? 0) + m[0].length;
  }
  body.push(d.text.slice(last));
  return (
    <div className="space-y-3">
      <p className="flex items-center gap-1.5 text-xs text-ink-3"><DocIcon kind={d.kind} size={14} />{d.kind} · {d.ts.slice(0, 10)}{d.author ? ` · ${d.author}` : ""}</p>
      <h3 className="text-sm font-semibold text-ink">{d.title}</h3>
      <p className="font-mono text-[11px] text-ink-3">{d.id} · {d.source}</p>
      <div className="whitespace-pre-wrap rounded-md bg-raised p-3 text-[13px] leading-relaxed text-ink-2">{body}</div>
      {d.mentions.length > 0 && (
        <div className="flex flex-wrap gap-1">{d.mentions.map((m) => <EntityChip key={m} id={m} onOpen={onOpen} />)}</div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ panel
const TABS: { tab: PanelTab; label: string }[] = [
  { tab: "node", label: "Node" }, { tab: "cypher", label: "Cypher" }, { tab: "source", label: "Source" }, { tab: "approvals", label: "Approvals" },
];

export default function RightPanel({ state, tenant, refreshKey, onTab, onClose, onOpen, onResult, onChanged }: {
  state: PanelState; tenant: string; refreshKey: number;
  onTab: (t: PanelTab) => void; onClose: () => void; onOpen: (id: string) => void;
  onResult: (label: string, r: AgentResult) => void; onChanged: () => void;
}) {
  const available = (t: PanelTab) => t === "approvals" || (t === "node" ? !!state.nodeId : t === "cypher" ? !!state.step : !!state.docId);
  return (
    <aside className="flex h-full w-[400px] shrink-0 flex-col border-l border-line bg-panel shadow-[-4px_0_12px_rgba(15,23,42,0.04)]">
      <div className="flex items-center gap-1 border-b border-line px-2 py-1.5">
        <div role="tablist" className="flex flex-1 gap-0.5">
          {TABS.map(({ tab, label }) => (
            <button key={tab} role="tab" aria-selected={state.tab === tab} disabled={!available(tab)} onClick={() => onTab(tab)}
                    className={`rounded px-2 py-1 text-xs font-medium disabled:opacity-35 ${state.tab === tab ? "bg-raised text-ink" : "text-ink-3 hover:text-ink"}`}>
              {label}
            </button>
          ))}
        </div>
        <button onClick={onClose} aria-label="Close panel" title="Close (Esc)" className="rounded p-1 text-ink-3 hover:bg-raised hover:text-ink"><X size={16} /></button>
      </div>
      <div className="flex-1 overflow-auto p-4">
        {state.tab === "node" && state.nodeId && <NodeTab tenant={tenant} id={state.nodeId} onOpen={onOpen} />}
        {state.tab === "cypher" && state.step && <CypherTab step={state.step} />}
        {state.tab === "source" && state.docId && <SourceTab tenant={tenant} id={state.docId} onOpen={onOpen} />}
        {state.tab === "approvals" && <Approvals tenant={tenant} refreshKey={refreshKey} onOpen={onOpen} onResult={onResult} onChanged={onChanged} />}
      </div>
    </aside>
  );
}
