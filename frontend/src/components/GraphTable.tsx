"use client";

import type { GraphEdge, GraphNode } from "@/lib/api";
import { EntityChip, ShapeSwatch } from "./ui";

/** Table view of what the canvas shows (FalkorDB Browser's Graph | Table). */
export default function GraphTable({ nodes, edges, onOpen }: { nodes: GraphNode[]; edges: GraphEdge[]; onOpen: (id: string) => void }) {
  const ids = new Set(nodes.map((n) => n.id));
  const shown = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  const th = "sticky top-0 bg-raised px-3 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-ink-3";
  return (
    <div className="grid h-full grid-cols-2 divide-x divide-line overflow-hidden">
      <div className="overflow-auto">
        <table className="w-full text-xs">
          <thead><tr><th className={th}>Label</th><th className={th}>Name</th><th className={th}>Id · {nodes.length}</th></tr></thead>
          <tbody>
            {nodes.map((n) => (
              <tr key={n.id} className="border-t border-line hover:bg-raised">
                <td className="px-3 py-1"><span className="flex items-center gap-1.5 text-ink-2"><ShapeSwatch label={n.label} />{n.label}</span></td>
                <td className="px-3 py-1 text-ink">{n.name}</td>
                <td className="px-3 py-1"><EntityChip id={n.id} name={n.id} onOpen={onOpen} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="overflow-auto">
        <table className="w-full text-xs">
          <thead><tr><th className={th}>Type · {shown.length}</th><th className={th}>From</th><th className={th}>To</th><th className={th}>State</th></tr></thead>
          <tbody>
            {shown.map((e, i) => (
              <tr key={i} className="border-t border-line hover:bg-raised">
                <td className="px-3 py-1 font-mono text-[11px] text-ink-2">{e.type}</td>
                <td className="px-3 py-1"><EntityChip id={e.source} onOpen={onOpen} /></td>
                <td className="px-3 py-1"><EntityChip id={e.target} onOpen={onOpen} /></td>
                <td className="px-3 py-1 text-[11px] text-warn">{e.superseded ? "superseded" : e.stale ? "stale" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
