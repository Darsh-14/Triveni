"use client";

import { useEffect, useState } from "react";
import type { ProgressEvent, Step, Track, Verification } from "@/lib/api";
import { SourceChips, TrackBadges } from "./Badges";

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
  memory?: string; // conversation / episode written for this answer
  verification?: Verification;
  startedAt?: number; // Date.now() when the request was sent, for the live elapsed counter
  progress?: ProgressEvent[]; // live status lines from the backend while an agent answer is pending
}

const PENDING_LABEL: Record<Entry["mode"], string> = {
  agent: "Agent is working",
  tool: "Running the tool on the graph",
  ingest: "Extracting facts and merging them into the graph",
};

/** Spinner, live elapsed seconds, the current step, and the trail of what was tried (providers, tools, fallbacks). */
function PendingStatus({ entry }: { entry: Entry }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = entry.startedAt ?? Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 250);
    return () => clearInterval(timer);
  }, [entry.startedAt]);
  const events = entry.progress ?? [];
  const current = events.at(-1)?.msg;
  return (
    <div className="mt-2 rounded-md border border-blue-200 bg-blue-50 p-2 text-xs text-blue-900">
      <div className="flex items-center gap-2">
        <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-blue-300 border-t-blue-700" />
        <span className="font-semibold">{PENDING_LABEL[entry.mode]}…</span>
        <span className="ml-auto tabular-nums text-blue-700">{elapsed}s</span>
      </div>
      {current && <p className="mt-1.5 font-medium">{current}</p>}
      {events.length > 1 && (
        <ol className="mt-1 space-y-0.5 text-[11px] text-blue-700/80">
          {events.slice(0, -1).map((e, i) => <li key={i}><span className="tabular-nums">{e.t.toFixed(1)}s</span> · {e.msg}</li>)}
        </ol>
      )}
      {entry.mode === "agent" && elapsed >= 8 && (
        <p className="mt-1.5 text-[11px] text-blue-700/80">Free-tier models can be slow or rate limited; Triveni falls back to the next provider, then to rules mode.</p>
      )}
    </div>
  );
}

const VERDICT: Record<string, string> = {
  verified: "bg-green-100 text-green-800 border-green-300",
  partially_verified: "bg-amber-100 text-amber-800 border-amber-300",
  unverified: "bg-red-100 text-red-800 border-red-300",
  no_citations: "bg-gray-100 text-gray-600 border-gray-300",
};

/** Deterministic proof check: every id the answer cites must exist in the graph and come from a tool result. */
function ProofBadge({ v }: { v: Verification }) {
  const label = v.verdict === "no_citations" ? "no ids cited"
    : `${v.verdict === "verified" ? "✓" : "!"} ${v.grounded.length}/${v.cited} claims grounded`;
  return (
    <div className="mt-2 text-[11px]">
      <span className={`rounded border px-1.5 py-0.5 font-semibold ${VERDICT[v.verdict]}`}
            title="Checked by code, not a model: each cited id must exist in this tenant's graph and appear in a tool result from this run">
        proof check: {label}
      </span>
      {v.unbacked.length > 0 && <span className="ml-1.5 text-amber-700">not shown by a tool: {v.unbacked.join(", ")}</span>}
      {v.unknown.length > 0 && <span className="ml-1.5 font-semibold text-red-700">not in the graph: {v.unknown.join(", ")}</span>}
    </div>
  );
}

export const entryTracks = (e: Entry): Track[] => [...new Set(e.steps.flatMap((s) => s.tracks))];
export const entrySources = (e: Entry): string[] => [...new Set(e.steps.flatMap((s) => s.sources))].sort();

interface Props {
  entry: Entry;
  active: boolean;
  onSelect: () => void;
  onCypher: (step: Step) => void;
  onDoc: (id: string) => void;
}

export default function EntryCard({ entry, active, onSelect, onCypher, onDoc }: Props) {
  return (
    <div onClick={onSelect}
         className={`cursor-pointer rounded-lg border bg-white p-3 shadow-sm ${active ? "border-gray-900" : "border-gray-200"}`}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-semibold text-gray-900">{entry.question}</p>
        <TrackBadges tracks={entryTracks(entry)} />
      </div>

      {entry.pending && <PendingStatus entry={entry} />}
      {entry.error && <p className="mt-2 rounded bg-red-50 p-2 text-xs text-red-700">{entry.error}</p>}
      {entry.answer && <p className="mt-2 whitespace-pre-wrap text-sm text-gray-800">{entry.answer}</p>}
      {entry.verification && <ProofBadge v={entry.verification} />}

      {entry.steps.length > 0 && (
        <ol className="mt-3 space-y-1.5 border-l-2 border-gray-200 pl-3">
          {entry.steps.map((s, i) => (
            <li key={i} className="text-xs">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-gray-400">{i + 1}.</span>
                <span className="rounded bg-gray-900 px-1.5 py-0.5 font-mono text-[11px] text-white">{s.tool}</span>
                <span className="font-mono text-[11px] text-gray-500">{JSON.stringify(s.input)}</span>
                <span className="text-[10px] uppercase text-gray-400">via {s.via} · {s.ms} ms</span>
                <button onClick={(ev) => { ev.stopPropagation(); onCypher(s); }}
                        className="rounded border border-gray-300 px-1.5 text-[10px] text-gray-600 hover:bg-gray-100">
                  Cypher
                </button>
              </div>
              {s.why && s.via !== "http" && <p className="mt-0.5 italic text-gray-500">why: {s.why}</p>}
              <p className={`mt-0.5 ${s.ok ? "text-gray-700" : "text-red-700"}`}>{s.explanation}</p>
            </li>
          ))}
        </ol>
      )}

      {entry.data !== undefined && (
        <details className="mt-2" onClick={(e) => e.stopPropagation()}>
          <summary className="cursor-pointer text-[11px] text-gray-500">Result data</summary>
          <pre className="mt-1 max-h-60 overflow-auto rounded bg-gray-50 p-2 text-[10px]">
            {JSON.stringify(entry.data, null, 2)}
          </pre>
        </details>
      )}

      <div className="mt-2" onClick={(e) => e.stopPropagation()}>
        <SourceChips sources={entrySources(entry)} onOpen={onDoc} />
      </div>
      {entry.model && <p className="mt-1 text-[10px] text-gray-400">model: {entry.model}</p>}
      {entry.memory && <p className="mt-0.5 text-[10px] text-blue-600">memory: {entry.memory}</p>}
    </div>
  );
}
