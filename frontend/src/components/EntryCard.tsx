"use client";

import type { Step, Track } from "@/lib/api";
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

      {entry.pending && <p className="mt-2 animate-pulse text-xs text-gray-500">Traversing the graph…</p>}
      {entry.error && <p className="mt-2 rounded bg-red-50 p-2 text-xs text-red-700">{entry.error}</p>}
      {entry.answer && <p className="mt-2 whitespace-pre-wrap text-sm text-gray-800">{entry.answer}</p>}

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
    </div>
  );
}
