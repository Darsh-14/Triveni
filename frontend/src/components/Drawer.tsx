"use client";

import type { Doc, Step } from "@/lib/api";
import { TrackBadges } from "./Badges";

export type DrawerContent = { kind: "cypher"; step: Step } | { kind: "doc"; doc: Doc | null; id: string; error?: string };

export default function Drawer({ content, onClose, onDoc }: {
  content: DrawerContent; onClose: () => void; onDoc: (id: string) => void;
}) {
  return (
    <aside className="absolute inset-y-0 right-0 z-10 flex w-[440px] flex-col border-l border-gray-200 bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2">
        <h2 className="text-sm font-semibold">{content.kind === "cypher" ? "Cypher used" : "Source document"}</h2>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-900" aria-label="Close">✕</button>
      </div>
      <div className="flex-1 space-y-3 overflow-auto p-4 text-sm">
        {content.kind === "cypher" ? (
          <>
            <div className="flex items-center gap-2">
              <span className="rounded bg-gray-900 px-1.5 py-0.5 font-mono text-xs text-white">{content.step.tool}</span>
              <TrackBadges tracks={content.step.tracks} />
            </div>
            <p className="text-xs text-gray-600">{content.step.explanation}</p>
            <pre className="overflow-auto whitespace-pre rounded bg-gray-900 p-3 font-mono text-[11px] leading-relaxed text-green-200">
              {content.step.cypher}
            </pre>
            <p className="text-xs font-semibold text-gray-700">Parameters</p>
            <pre className="overflow-auto rounded bg-gray-50 p-2 font-mono text-[11px]">
              {JSON.stringify(content.step.params, null, 2)}
            </pre>
            <p className="text-[11px] text-gray-500">
              Values are always passed as parameters; only validated integers (depth, limit) are written into the query.
            </p>
          </>
        ) : content.error ? (
          <p className="text-red-700">{content.error}</p>
        ) : !content.doc ? (
          <p className="animate-pulse text-gray-500">Loading {content.id}…</p>
        ) : (
          <>
            <p className="font-mono text-xs text-gray-500">{content.doc.id} · {content.doc.kind}</p>
            <h3 className="font-semibold">{content.doc.title}</h3>
            <p className="text-xs text-gray-500">
              {content.doc.ts}{content.doc.author ? ` · by ${content.doc.author}` : ""} · {content.doc.source}
            </p>
            <pre className="whitespace-pre-wrap rounded bg-gray-50 p-3 font-sans text-[13px]">{content.doc.text}</pre>
            {content.doc.mentions.length > 0 && (
              <div className="flex flex-wrap gap-1">
                <span className="text-[11px] text-gray-500">Mentions:</span>
                {content.doc.mentions.map((m) => (
                  <span key={m} className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px]">
                    {m.startsWith("doc:") ? <button onClick={() => onDoc(m)}>{m}</button> : m}
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
