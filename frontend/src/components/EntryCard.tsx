"use client";

import { Fragment, useEffect, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, CircleAlert, CircleCheck, CircleX, LoaderCircle } from "lucide-react";
import { api, type Doc, type Guard, type ProgressEvent, type Step, type Track, type Verification } from "@/lib/api";
import { docKindOfId, ID_PATTERN } from "@/lib/entities";
import Callouts from "./Callouts";
import StepTimeline from "./StepTimeline";
import { Chip, DocIcon, EntityChip, TrackTags, type Tone } from "./ui";

export interface Entry {
  id: string;
  question: string;
  mode: "agent" | "tool" | "ingest";
  pending: boolean;
  answer?: string;
  steps: Step[];
  error?: string;
  data?: unknown;
  model?: string;
  fallbacks?: string[];
  conversationId?: string;
  episode?: string;
  restored?: boolean;
  verification?: Verification;
  guard?: Guard;  // the model's draft was rejected by the proof check and replaced by the tool results
  startedAt?: number;
  ms?: number; // total time once done
  progress?: ProgressEvent[];
}

export const entryTracks = (e: Entry): Track[] => [...new Set(e.steps.flatMap((s) => s.tracks))];
export const entrySources = (e: Entry): string[] => [...new Set(e.steps.flatMap((s) => s.sources))].sort();

interface Handlers {
  onOpen: (id: string) => void;          // entity or document id -> right panel
  onHover: (id: string | null) => void;  // highlight on canvas
  onCypher: (step: Step) => void;
  onStep: (index: number | null) => void; // highlight one step's paths
  onApprovals: () => void;
  onCancel: () => void;
}

// ------------------------------------------------------------------ pending: spinner, elapsed, tool chips
function Pending({ entry, onCancel }: { entry: Entry; onCancel: () => void }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, []);
  const elapsed = Math.max(0, Math.floor((now - (entry.startedAt ?? now)) / 1000));
  const events = entry.progress ?? [];
  const tools = events.map((e) => /calling (\S+) over MCP/.exec(e.msg)?.[1]).filter(Boolean) as string[];
  const failed = events.map((e) => /^(\S+) unavailable/.exec(e.msg)?.[1]).filter(Boolean) as string[];
  const provider = [...events].reverse().map((e) => /^(\w+): /.exec(e.msg)?.[1]).find(Boolean);
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs" aria-live="polite">
      <LoaderCircle size={14} className="animate-spin text-accent" aria-label="Working" />
      <span className="tabular-nums text-ink-3">{elapsed}s</span>
      {failed.map((p) => <Chip key={p} tone="muted"><span className="line-through">{p}</span></Chip>)}
      {provider && <Chip tone="info">{provider}</Chip>}
      {tools.map((t, i) => (
        <Chip key={i} tone={i === tools.length - 1 ? "info" : "ok"}>
          <span className="font-mono">{t}</span>{i === tools.length - 1 ? " …" : " ✓"}
        </Chip>
      ))}
      {entry.mode === "agent" && <button onClick={onCancel} className="ml-auto text-ink-3 hover:text-ink">Cancel</button>}
    </div>
  );
}

// ------------------------------------------------------------------ verdict (deterministic proof check)
const VERDICT: Record<Verification["verdict"], { word: string; tone: Tone; Icon: typeof CircleCheck }> = {
  verified: { word: "Verified", tone: "ok", Icon: CircleCheck },
  partially_verified: { word: "Partly verified", tone: "warn", Icon: CircleAlert },
  unverified: { word: "Unverified", tone: "bad", Icon: CircleX },
  no_citations: { word: "No citations", tone: "muted", Icon: CircleAlert },
};

function VerdictChip({ v }: { v: Verification }) {
  const { word, tone, Icon } = VERDICT[v.verdict];
  return (
    <Chip tone={tone}>
      <Icon size={12} aria-hidden />{word}{v.verdict !== "no_citations" && <span className="tabular-nums"> {v.grounded.length}/{v.cited}</span>}
    </Chip>
  );
}

/** The proof check rejected the model's draft (it named something no tool returned); the answer shown is the tools'. */
function GuardNotice({ guard }: { guard: Guard }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2 rounded-md border border-warn/30 bg-warn-soft px-2 py-1.5 text-xs text-warn">
      <p>
        <span className="font-semibold">Model draft rejected</span>: it {guard.reason}. Showing only what the graph tools
        returned. <button onClick={() => setOpen(!open)} className="underline">{open ? "hide" : "show"} draft</button>
      </p>
      {open && <p className="mt-1 whitespace-pre-wrap text-ink-3 line-through decoration-warn/40">{guard.draft}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ sources row (cards above the answer)
const docCache = new Map<string, Promise<Doc | null>>();
function useDocs(tenant: string, ids: string[]) {
  const [docs, setDocs] = useState<Record<string, Doc | null>>({});
  const key = ids.join(",");
  useEffect(() => {
    let live = true;
    ids.forEach((id) => {
      const k = `${tenant}|${id}`;
      if (!docCache.has(k)) docCache.set(k, api.document(tenant, id).catch(() => null));
      docCache.get(k)!.then((d) => live && setDocs((m) => ({ ...m, [id]: d })));
    });
    return () => { live = false; };
  }, [tenant, key]); // eslint-disable-line react-hooks/exhaustive-deps
  return docs;
}

function SourcesRow({ tenant, ids, onOpen }: { tenant: string; ids: string[]; onOpen: (id: string) => void }) {
  const docs = useDocs(tenant, ids);
  if (!ids.length) return null;
  return (
    <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
      {ids.map((id, i) => {
        const d = docs[id];
        const kind = d?.kind ?? docKindOfId(id);
        return (
          <button key={id} onClick={(e) => { e.stopPropagation(); onOpen(id); }} title={id}
                  className="flex w-44 shrink-0 flex-col gap-0.5 rounded-md border border-line bg-raised px-2 py-1.5 text-left hover:border-line-strong">
            <span className="flex items-center gap-1 text-[11px] text-ink-3">
              <span className="tabular-nums">{i + 1}</span><DocIcon kind={kind} size={12} />{kind}
            </span>
            <span className="line-clamp-2 text-xs font-medium leading-snug text-ink">{d?.title ?? id}</span>
          </button>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ answer text: ids become citation chips
const CITED = new RegExp(String.raw`\s?[(\[]\s*(${ID_PATTERN.source})\s*[)\]]|${ID_PATTERN.source}`, "gi");
function inline(text: string, h: Handlers, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  // **bold**, `code` and the model's 【tool】 citations; everything else is text with id chips
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|【[^】]+】)/g);
  parts.forEach((part, pi) => {
    if (/^`[^`]+`$/.test(part) && !new RegExp(`^\`${ID_PATTERN.source}\`$`, "i").test(part)) {
      out.push(<code key={`${key}-${pi}`} className="rounded bg-raised px-1 font-mono text-[12px] text-ink">{part.slice(1, -1)}</code>);
      return;
    }
    if (part.startsWith("【")) {
      out.push(<span key={`${key}-${pi}`} className="ml-0.5 rounded bg-raised px-1 font-mono text-[11px] text-ink-3">{part.slice(1, -1)}</span>);
      return;
    }
    const bold = part.startsWith("**") && part.endsWith("**");
    const body = bold ? part.slice(2, -2) : part.replace(/^`|`$/g, "");
    let last = 0;
    const nodes: ReactNode[] = [];
    // "(svc:x)" or "[svc:x]" right after a name is a citation: icon-only marker; a bare id is a full chip
    for (const m of body.matchAll(CITED)) {
      nodes.push(body.slice(last, m.index));
      const id = m[1] ?? m[0];
      nodes.push(<EntityChip key={`${key}-${pi}-${m.index}`} id={id} compact={Boolean(m[1])} onOpen={h.onOpen} onHover={h.onHover} />);
      last = (m.index ?? 0) + m[0].length;
    }
    nodes.push(body.slice(last));
    out.push(bold ? <strong key={`${key}-${pi}`} className="font-semibold text-ink">{nodes}</strong> : <Fragment key={`${key}-${pi}`}>{nodes}</Fragment>);
  });
  return out;
}

function AnswerText({ text, h }: { text: string; h: Handlers }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    blocks.push(<Tag key={`l${blocks.length}`} className={`${list.ordered ? "list-decimal" : "list-disc"} space-y-1 pl-5`}>
      {list.items.map((it, i) => <li key={i}>{inline(it, h, `l${blocks.length}-${i}`)}</li>)}</Tag>);
    list = null;
  };
  lines.forEach((line, i) => {
    const m = /^\s*(?:([-*•])|(\d+)[.)])\s+(.*)$/.exec(line);
    if (m) {
      const ordered = Boolean(m[2]);
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] }; }
      list.items.push(m[3]);
      return;
    }
    flush();
    const heading = /^#{1,4}\s+(.*)$/.exec(line);
    if (heading) blocks.push(<p key={i} className="font-semibold text-ink">{inline(heading[1], h, `h${i}`)}</p>);
    else if (line.trim()) blocks.push(<p key={i}>{inline(line, h, `p${i}`)}</p>);
  });
  flush();
  return <div className="max-w-[65ch] space-y-2 text-sm leading-relaxed text-ink-2">{blocks}</div>;
}

// ------------------------------------------------------------------ card
export default function EntryCard({ entry, tenant, active, focusStep, onSelect, ...h }: {
  entry: Entry; tenant: string; active: boolean; focusStep: number | null; onSelect: () => void;
} & Handlers) {
  const [stepsOpen, setStepsOpen] = useState<boolean | null>(null); // null: open by default for short traces
  const showSteps = stepsOpen ?? entry.steps.length <= 6;
  const [showDetails, setShowDetails] = useState(false);
  const sources = entrySources(entry);
  const tracks = entryTracks(entry);

  return (
    <article className={`rounded-lg border bg-panel p-4 ${active ? "border-accent ring-1 ring-accent/20" : "border-line"}`}>
      <button onClick={onSelect} className="w-full text-left">
        <h3 className="text-base font-semibold leading-snug text-ink">{entry.question}</h3>
      </button>

      {entry.pending && <Pending entry={entry} onCancel={h.onCancel} />}
      {entry.error && <p className="mt-2 rounded-md bg-bad-soft px-2 py-1.5 text-xs text-bad">{entry.error}</p>}

      {!entry.pending && !entry.error && (entry.steps.length > 0 || entry.verification || entry.model) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {entry.verification && <VerdictChip v={entry.verification} />}
          {entry.steps.length > 0 && (
            <button onClick={() => setStepsOpen(!showSteps)} aria-expanded={showSteps}
                    className="inline-flex items-center gap-0.5 rounded border border-line bg-panel px-1.5 py-0.5 text-xs font-medium text-ink-2 hover:bg-raised">
              {showSteps ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              {entry.steps.length} tool{entry.steps.length > 1 ? "s" : ""}
            </button>
          )}
          {entry.ms !== undefined && <span className="text-xs tabular-nums text-ink-3">{(entry.ms / 1000).toFixed(1)} s</span>}
          {entry.fallbacks?.map((f) => <Chip key={f}><span className="line-through">{f.split(":")[0]}</span></Chip>)}
          {entry.model && <Chip tone="info">{entry.model}</Chip>}
          <span className="ml-auto"><TrackTags tracks={tracks} /></span>
        </div>
      )}

      {entry.verification && (entry.verification.unbacked.length > 0 || entry.verification.unknown.length > 0) && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {entry.verification.unbacked.map((id) => <Chip key={id} tone="warn">{id}</Chip>)}
          {entry.verification.unknown.map((id) => <Chip key={id} tone="bad">{id}</Chip>)}
        </div>
      )}

      {entry.guard && <GuardNotice guard={entry.guard} />}

      {showSteps && entry.steps.length > 0 && (
        <StepTimeline steps={entry.steps} events={entry.progress ?? []} totalMs={entry.ms} focusStep={focusStep}
                      onStep={h.onStep} onCypher={h.onCypher} />
      )}

      {sources.length > 0 && <div className="mt-3"><SourcesRow tenant={tenant} ids={sources} onOpen={h.onOpen} /></div>}

      {entry.answer && <div className="mt-3"><AnswerText text={entry.answer} h={h} /></div>}

      {entry.steps.length > 0 && (
        <div className="mt-3">
          <Callouts steps={entry.steps} onOpen={h.onOpen} onHover={h.onHover} onApprovals={h.onApprovals} />
        </div>
      )}

      {!entry.pending && (entry.data !== undefined || entry.conversationId || entry.steps.some((s) => s.data)) && (
        <div className="mt-3">
          <button onClick={() => setShowDetails((v) => !v)} aria-expanded={showDetails}
                  className="inline-flex items-center gap-0.5 text-xs text-ink-3 hover:text-ink">
            {showDetails ? <ChevronDown size={12} /> : <ChevronRight size={12} />}Details
          </button>
          {showDetails && (
            <div className="mt-1.5 space-y-1.5">
              <div className="flex flex-wrap gap-1">
                {entry.conversationId && <EntityChip id={entry.conversationId} onOpen={h.onOpen} />}
                {entry.episode && <EntityChip id={entry.episode} onOpen={h.onOpen} />}
              </div>
              <pre className="max-h-64 overflow-auto rounded-md bg-raised p-2 font-mono text-[11px] text-ink-2">
                {JSON.stringify(entry.data ?? entry.steps.map((s) => ({ tool: s.tool, data: s.data })), null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
