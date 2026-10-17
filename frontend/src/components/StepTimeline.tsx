"use client";

import { Code } from "lucide-react";
import type { ProgressEvent, Step } from "@/lib/api";

/* Agent steps as a timeline (Langfuse / LangSmith trace view): one bar per tool call, placed at the moment the
   agent called it and as long as the call took. Gaps between bars are the model thinking.
   Start times come from the live progress events ("calling X over MCP" at t seconds); a direct tool run or a
   restored answer has none, so its bars are laid end to end. */

// What each tool's result means, stated by the tool itself (tools/base.py): an empty traversal is never "safe".
const OUTCOME: Record<string, { label: string; cls: string; title: string }> = {
  unknown_entity: { label: "unknown name", cls: "text-bad", title: "The name matches nothing in this graph; the tool did not run" },
  not_in_graph: { label: "absent", cls: "text-warn", title: "The entity exists; the fact asked about is not in the graph" },
  from_memory: { label: "from memory", cls: "text-accent", title: "Answered from earlier episodes" },
  recorded: { label: "recorded", cls: "text-ok", title: "Written to the graph" },
};

const resolvedTitle = (s: Step) =>
  (s.resolved ?? []).filter((r) => r.query !== r.id).map((r) => `"${r.query}" -> ${r.id} (${r.how.replace("_", " ")})`).join("; ");

function startTimes(steps: Step[], events: ProgressEvent[]): number[] {
  const calls = events.map((e) => ({ tool: /calling (\S+) over MCP/.exec(e.msg)?.[1], ms: e.t * 1000 })).filter((c) => c.tool);
  let cursor = 0;
  let elapsed = 0;
  return steps.map((s) => {
    const i = calls.findIndex((c, k) => k >= cursor && c.tool === s.tool);
    const start = i >= 0 ? calls[i].ms : elapsed;
    if (i >= 0) cursor = i + 1;
    elapsed = start + s.ms;
    return start;
  });
}

export default function StepTimeline({ steps, events, totalMs, focusStep, onStep, onCypher }: {
  steps: Step[]; events: ProgressEvent[]; totalMs?: number; focusStep: number | null;
  onStep: (i: number | null) => void; onCypher: (s: Step) => void;
}) {
  const starts = startTimes(steps, events);
  const total = Math.max(totalMs ?? 0, ...steps.map((s, i) => starts[i] + s.ms), 1);
  const pct = (ms: number) => `${Math.min(100, (ms / total) * 100)}%`;
  const fmt = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);

  return (
    <div className="mt-2 rounded-md border border-line">
      <ol className="divide-y divide-line">
        {steps.map((s, i) => (
          <li key={i} className={`grid grid-cols-[1rem_minmax(0,9.5rem)_1fr_3.5rem_1.25rem] items-center gap-2 px-2 py-1.5 text-xs ${focusStep === i ? "bg-accent-soft" : ""}`}>
            <span className="tabular-nums text-ink-3">{i + 1}</span>
            <button onClick={() => onStep(focusStep === i ? null : i)}
                    title={[s.explanation, resolvedTitle(s)].filter(Boolean).join(" | resolved: ")} className="min-w-0 text-left">
              <span className={`block truncate font-mono font-medium ${s.ok ? "text-ink" : "text-bad"}`}>
                {s.tool}
                {s.outcome && OUTCOME[s.outcome] && (
                  <span className={`ml-1.5 font-sans text-[10px] font-semibold uppercase ${OUTCOME[s.outcome].cls}`}
                        title={OUTCOME[s.outcome].title}>{OUTCOME[s.outcome].label}</span>
                )}
              </span>
              <span className="block truncate font-mono text-[11px] text-ink-3">{Object.values(s.input).map(String).join(" · ")}</span>
            </button>
            <button onClick={() => onStep(focusStep === i ? null : i)} aria-label={`Highlight step ${i + 1}`}
                    className="relative h-4 rounded-sm bg-raised">
              <span className={`absolute inset-y-0 rounded-sm ${!s.ok ? "bg-bad" : focusStep === i ? "bg-accent" : "bg-accent/60"}`}
                    style={{ left: pct(starts[i]), width: `max(3px, ${pct(s.ms)})` }} />
            </button>
            <span className="text-right tabular-nums text-ink-3">{fmt(s.ms)}</span>
            {s.cypher ? (
              <button onClick={() => onCypher(s)} title="Cypher" aria-label={`Cypher for ${s.tool}`}
                      className="rounded p-0.5 text-ink-3 hover:bg-raised hover:text-ink"><Code size={14} /></button>
            ) : <span />}
          </li>
        ))}
      </ol>
      <div className="grid grid-cols-[1rem_minmax(0,9.5rem)_1fr_3.5rem_1.25rem] gap-2 border-t border-line px-2 py-1 text-[11px] tabular-nums text-ink-3">
        <span /><span />
        <span className="flex justify-between"><span>0</span><span>{fmt(Math.round(total / 2))}</span><span>{fmt(total)}</span></span>
        <span /><span />
      </div>
    </div>
  );
}
