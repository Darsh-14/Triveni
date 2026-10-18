"use client";

import { Fragment, useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, Copy, Expand, X } from "lucide-react";
import { api, type Doc, type NodeDetail, type Step } from "@/lib/api";
import { ID_PATTERN } from "@/lib/entities";
import type { AgentResult } from "@/lib/api";
import Approvals from "./Coordination";
import { EntityChip, ShapeSwatch, TrackTags } from "./ui";

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
      out.push(<span key={`${key}-${m.index}`} className="font-semibold text-ink">{m[0]}</span>);
      i = (m.index ?? 0) + m[0].length;
    }
    out.push(s.slice(i));
  };
  for (const m of text.matchAll(token)) {
    pushPlain(text.slice(last, m.index), `p${last}`);
    const cls = m[1] ? "text-accent-ink" : m[2] ? "text-ok" : m[3] ? "text-ink-3 italic" : "text-ink-2";
    out.push(<span key={`t${m.index}`} className={cls}>{m[0]}</span>);
    last = (m.index ?? 0) + m[0].length;
  }
  pushPlain(text.slice(last), "end");
  return <pre className="overflow-auto whitespace-pre rounded border border-line bg-raised p-3 font-mono text-[12px] leading-relaxed text-ink-2">{out}</pre>;
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
// Entity page (Backstage / Port catalog style): key facts, then the node's edges grouped by what they reach.
const SECTION_ORDER = ["Team", "Person", "Service", "Incident", "Deployment", "Decision", "Document",
                       "Episode", "Lesson", "Procedure", "Action", "Handoff", "Agent"];
const PLURAL: Record<string, string> = { Person: "People" };
const FACT_KEYS = ["tier", "lang", "role", "severity", "status", "kind", "version", "ts", "ts_open", "ts_close", "confidence",
                   "success_count", "fail_count"];
const FOLD_AT = 6;

function Section({ title, label, count, children, defaultOpen = true }: {
  title: string; label?: string; count: number; children: ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section>
      <button onClick={() => setOpen(!open)} aria-expanded={open}
              className="mb-1 flex w-full items-center gap-1.5 text-xs font-medium text-ink-2 hover:text-ink">
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        {label && <ShapeSwatch label={label} size={10} />}
        <span className="flex-1 text-left">{title}</span>
        <span className="tabular-nums">{count}</span>
      </button>
      {open && children}
    </section>
  );
}

function NodeTab({ tenant, id, onOpen, onExpand }: {
  tenant: string; id: string; onOpen: (id: string) => void; onExpand: (id: string, depth: 1 | 2) => void;
}) {
  const [node, setNode] = useState<{ id: string; data: NodeDetail | null; error?: string } | null>(null);
  const [unfolded, setUnfolded] = useState<Set<string>>(new Set());
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

  // key facts: who owns it, who is on call, which team, and a few scalar properties
  const incoming = (type: string) => current.filter((e) => e.type === type && !e.out);
  const outgoing = (type: string) => current.filter((e) => e.type === type && e.out);
  const people: [string, typeof current][] = [
    ["Owner", incoming("OWNS")], ["On call", incoming("ON_CALL_FOR")], ["Team", outgoing("MEMBER_OF")],
    ["Owns", outgoing("OWNS")], ["On call for", outgoing("ON_CALL_FOR")],
  ];
  const facts = FACT_KEYS.filter((k) => n.properties[k] !== undefined && n.properties[k] !== null && n.properties[k] !== "")
    .map((k) => [k, String(n.properties[k])]);

  // edges grouped by the label of the node they reach
  const groups = new Map<string, typeof current>();
  current.forEach((e) => groups.set(e.label, [...(groups.get(e.label) ?? []), e]));
  const order = [...groups.keys()].sort((x, y) =>
    (SECTION_ORDER.indexOf(x) + 1 || 99) - (SECTION_ORDER.indexOf(y) + 1 || 99) || x.localeCompare(y));

  const row = (e: (typeof current)[number], i: number, old = false) => (
    <tr key={i} className="border-t border-line">
      <td className="whitespace-nowrap py-1 pr-2 font-mono text-[11px] text-ink-3">
        <span className="inline-flex items-center gap-1">
          {e.out ? <ArrowRight size={11} aria-label="outgoing" /> : <ArrowLeft size={11} aria-label="incoming" />}
          <span className={old ? "line-through" : ""}>{e.type}</span>
        </span>
      </td>
      <td className="w-full max-w-0 py-1"><EntityChip id={e.id} name={e.name} struck={old} onOpen={onOpen} /></td>
      <td className="max-w-28 py-1 pl-2 text-right">{e.source_doc && <EntityChip id={e.source_doc} onOpen={onOpen} />}</td>
    </tr>
  );
  const props = Object.entries(n.properties).filter(([k]) => k !== "id");

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2">
        <ShapeSwatch label={n.label} size={18} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink">{String(n.properties.name ?? n.properties.title ?? n.id)}</p>
          <p className="flex items-center gap-1 font-mono text-[11px] text-ink-3">{n.label} · {n.id} <CopyButton text={n.id} /></p>
        </div>
      </div>

      <div className="flex gap-1.5">
        {([1, 2] as const).map((d) => (
          <button key={d} onClick={() => onExpand(n.id, d)}
                  className="inline-flex items-center gap-1 rounded border border-line-strong px-2 py-1 text-xs font-medium text-ink-2 hover:bg-raised">
            <Expand size={12} />+{d} hop{d > 1 ? "s" : ""}
          </button>
        ))}
      </div>

      {(people.some(([, l]) => l.length) || facts.length > 0) && (
        <div className="grid grid-cols-[6rem_1fr] gap-x-2 gap-y-1.5 border-y border-line py-2.5 text-xs">
          {people.filter(([, l]) => l.length).map(([k, l]) => (
            <Fragment key={k}>
              <span className="pt-0.5 text-ink-3">{k}</span>
              <span className="flex flex-wrap gap-1">{l.map((e) => <EntityChip key={e.id} id={e.id} name={e.name} onOpen={onOpen} />)}</span>
            </Fragment>
          ))}
          {facts.map(([k, v]) => (
            <Fragment key={k}>
              <span className="font-mono text-[11px] text-ink-3">{k}</span>
              <span className="text-ink-2">{v}</span>
            </Fragment>
          ))}
        </div>
      )}

      {order.map((label) => {
        const list = groups.get(label)!;
        const open = unfolded.has(label) || list.length <= FOLD_AT;
        return (
          <Section key={label} title={PLURAL[label] ?? `${label}s`} label={label} count={list.length}>
            <table className="w-full text-xs"><tbody>{(open ? list : list.slice(0, FOLD_AT)).map((e, i) => row(e, i))}</tbody></table>
            {!open && (
              <button onClick={() => setUnfolded(new Set([...unfolded, label]))}
                      className="mt-1 text-xs font-medium text-accent-ink hover:underline">+{list.length - FOLD_AT}</button>
            )}
          </Section>
        );
      })}

      {past.length > 0 && (
        <Section title="History" count={past.length}>
          <table className="w-full text-xs"><tbody>{past.map((e, i) => row(e, i, true))}</tbody></table>
        </Section>
      )}

      <Section title="Properties" count={props.length} defaultOpen={false}>
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
      </Section>
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
              <td className="w-28 py-1 pr-2 font-mono text-[11px] text-accent-ink">${k}</td>
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
    body.push(<button key={m.index} onClick={() => onOpen(m[0])} className="font-mono text-accent-ink underline decoration-dotted">{m[0]}</button>);
    last = (m.index ?? 0) + m[0].length;
  }
  body.push(d.text.slice(last));
  return (
    <div className="space-y-3">
      <p className="font-mono text-xs text-ink-3">{d.kind} · {d.ts.slice(0, 10)}{d.author ? ` · ${d.author}` : ""}</p>
      <h3 className="text-sm font-semibold text-ink">{d.title}</h3>
      <p className="font-mono text-[11px] text-ink-3">{d.id} · {d.source}</p>
      <div className="whitespace-pre-wrap rounded bg-raised p-3 text-[13px] leading-relaxed text-ink-2">{body}</div>
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

export default function RightPanel({ width, state, tenant, refreshKey, onTab, onClose, onOpen, onResult, onChanged, onExpand }: {
  width: number; state: PanelState; tenant: string; refreshKey: number; onExpand: (id: string, depth: 1 | 2) => void;
  onTab: (t: PanelTab) => void; onClose: () => void; onOpen: (id: string) => void;
  onResult: (label: string, r: AgentResult) => void; onChanged: () => void;
}) {
  const available = (t: PanelTab) => t === "approvals" || (t === "node" ? !!state.nodeId : t === "cypher" ? !!state.step : !!state.docId);
  return (
    <aside style={{ width }} className="flex h-full shrink-0 flex-col overflow-hidden rounded-xl border border-line bg-panel">
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
        {state.tab === "node" && state.nodeId && <NodeTab key={state.nodeId} tenant={tenant} id={state.nodeId} onOpen={onOpen} onExpand={onExpand} />}
        {state.tab === "cypher" && state.step && <CypherTab step={state.step} />}
        {state.tab === "source" && state.docId && <SourceTab tenant={tenant} id={state.docId} onOpen={onOpen} />}
        {state.tab === "approvals" && <Approvals tenant={tenant} refreshKey={refreshKey} onOpen={onOpen} onResult={onResult} onChanged={onChanged} />}
      </div>
    </aside>
  );
}
