"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Core, ElementDefinition, LayoutOptions, NodeSingular } from "cytoscape";
import { Eye, EyeOff, Maximize, Network, Orbit, Search, Share2, SunDim, ZoomIn, ZoomOut } from "lucide-react";
import type { GraphEdge, GraphNode } from "@/lib/api";
import { styleOf } from "@/lib/entities";
import { IconButton, ShapeSwatch } from "./ui";

export type LayoutName = "force" | "tree" | "radial";

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  focus: Set<string> | null;  // node ids + edge keys of one step: everything else fades
  hover: string | null;       // entity hovered in the thread
  roots: string[];            // queried node(s): tree/radial centre
  layout: LayoutName;
  onLayout: (l: LayoutName) => void;
  selected: string | null;
  onSelect: (id: string | null) => void;
}

export const edgeKey = (e: GraphEdge) => `${e.type}:${e.source}->${e.target}`;

const STYLE = [
  { selector: "node", style: {
      "background-color": "data(colour)", shape: "data(shape)", label: "data(label)", width: 22, height: 22,
      "font-size": 11, color: "#334155", "min-zoomed-font-size": 8, "text-valign": "bottom", "text-margin-y": 4,
      "text-wrap": "ellipsis", "text-max-width": "120px", "border-width": 0 } },
  { selector: "node.root", style: { width: 30, height: 30, "border-width": 3, "border-color": "#0f172a", "font-weight": "bold", "font-size": 11 } },
  { selector: "node:selected", style: { "border-width": 3, "border-color": "#4f46e5", "overlay-opacity": 0 } },
  { selector: "node.hover", style: { "border-width": 3, "border-color": "#4f46e5", width: 30, height: 30, "z-index": 20 } },
  { selector: "edge", style: {
      width: 1.5, "line-color": "#94a3b8", "target-arrow-color": "#94a3b8", "target-arrow-shape": "triangle",
      "curve-style": "bezier", "arrow-scale": 0.8, label: "data(label)", "font-size": 10, color: "#5b6577",
      "min-zoomed-font-size": 7, "text-background-color": "#ffffff", "text-background-opacity": 0.9,
      "text-background-padding": "1px" } },
  { selector: "edge.overview", style: { label: "", width: 1, "line-color": "#cbd5e1", "target-arrow-color": "#cbd5e1" } },
  { selector: "edge.old", style: { "line-style": "dashed", "line-color": "#b45309", "target-arrow-color": "#b45309", color: "#b45309" } },
  { selector: ".faded", style: { opacity: 0.12, "text-opacity": 0 } },
  { selector: ".off", style: { display: "none" } },
];

function layoutOptions(name: LayoutName, cy: Core, roots: string[], count: number): LayoutOptions {
  const rootEls = roots.reduce((c, id) => c.union(cy.getElementById(id)), cy.collection());
  if (name === "tree") {
    return { name: "breadthfirst", directed: false, roots: rootEls.nonempty() ? rootEls : undefined, padding: 30,
             spacingFactor: 1.15, animate: false } as LayoutOptions;
  }
  if (name === "radial") {
    const rootIds = new Set(roots);
    return { name: "concentric", padding: 30, animate: false, minNodeSpacing: 18, levelWidth: () => 1,
             concentric: (n: NodeSingular) => (rootIds.has(n.id()) ? 100 : n.degree(false)) } as LayoutOptions;
  }
  return { name: "fcose", animate: false, randomize: true, padding: 40, quality: "default",
           nodeRepulsion: () => (count > 30 ? 9000 : 5000), idealEdgeLength: () => (count > 30 ? 90 : 70),
           nodeSeparation: 60 } as LayoutOptions;
}

/** Fit the graph, but never blow a small evidence graph up past 125%. */
function fitCapped(c: Core | null) {
  if (!c || !c.elements().length) return;
  c.fit(undefined, 48);
  if (c.zoom() > 1.25) { c.zoom(1.25); c.center(); }
}

export default function GraphCanvas({ nodes, edges, focus, hover, roots, layout, onLayout, selected, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [ready, setReady] = useState(false);
  const [dim, setDim] = useState(false);
  const [hiddenLabels, setHiddenLabels] = useState<Set<string>>(new Set());
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [tip, setTip] = useState<{ x: number; y: number; name: string; label: string; id: string } | null>(null);
  const handlers = useRef({ onSelect });
  useEffect(() => { handlers.current = { onSelect }; }, [onSelect]);

  // one instance for the page lifetime
  useEffect(() => {
    let disposed = false;
    let observer: ResizeObserver | null = null;
    (async () => {
      const cytoscape = (await import("cytoscape")).default; // browser-only
      const fcose = (await import("cytoscape-fcose")).default;
      if (disposed || !container.current) return;
      try { cytoscape.use(fcose); } catch { /* already registered (fast refresh) */ }
      cy.current = cytoscape({ container: container.current, style: STYLE as never, minZoom: 0.15, maxZoom: 2.5 });
      cy.current.on("tap", "node", (e) => handlers.current.onSelect(e.target.id()));
      cy.current.on("tap", (e) => { if (e.target === cy.current) handlers.current.onSelect(null); });
      cy.current.on("mouseover", "node", (e) => {
        const p = e.target.renderedPosition();
        setTip({ x: p.x, y: p.y, name: e.target.data("name"), label: e.target.data("kind"), id: e.target.id() });
      });
      cy.current.on("mouseout", "node", () => setTip(null));
      cy.current.on("viewport", () => setTip(null));
      // the right panel opening or closing changes the canvas size: re-measure and re-fit
      const ro = new ResizeObserver(() => { cy.current?.resize(); fitCapped(cy.current); });
      ro.observe(container.current);
      observer = ro;
      setReady(true);
    })();
    return () => { disposed = true; observer?.disconnect(); cy.current?.destroy(); cy.current = null; };
  }, []);

  // f = fit, d = dim (ignored while typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "f") fitCapped(cy.current);
      if (e.key === "d") setDim((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const overview = useMemo(() => !roots.length && edges.every((e) => e.type === "DEPENDS_ON" || e.type === "OWNS"), [roots, edges]);

  // new elements: replace and lay out (instance kept)
  useEffect(() => {
    const c = cy.current;
    if (!c || !ready) return;
    const ids = new Set(nodes.map((n) => n.id));
    const rootIds = new Set(roots);
    const els: ElementDefinition[] = [
      ...nodes.map((n) => ({
        data: { id: n.id, name: n.name, label: n.name, kind: n.label, colour: styleOf(n.label).colour, shape: styleOf(n.label).shape },
        classes: rootIds.has(n.id) ? "root" : "",
      })),
      ...edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({
        data: { id: edgeKey(e), source: e.source, target: e.target, type: e.type,
                label: e.superseded || e.stale ? `${e.type} · ${e.superseded ? "superseded" : "stale"}` : e.type },
        classes: [e.superseded || e.stale ? "old" : "", overview ? "overview" : ""].join(" ").trim(),
      })),
    ];
    c.batch(() => { c.elements().remove(); c.add(els); });
    c.layout(layoutOptions(layout, c, roots, nodes.length)).run();
    fitCapped(c);
  }, [nodes, edges, roots, ready, overview]); // eslint-disable-line react-hooks/exhaustive-deps

  // layout switch only
  useEffect(() => {
    const c = cy.current;
    if (!c || !ready || !c.nodes().length) return;
    c.layout(layoutOptions(layout, c, roots, c.nodes().length)).run();
    fitCapped(c);
  }, [layout]); // eslint-disable-line react-hooks/exhaustive-deps

  // classes: focus (one step), dim (selection neighbourhood), filters, hover, selection
  useEffect(() => {
    const c = cy.current;
    if (!c || !ready) return;
    c.batch(() => {
      c.elements().removeClass("faded off hover");
      if (focus) c.elements().filter((el) => !focus.has(el.id())).addClass("faded");
      if (dim && selected) {
        const keep = c.getElementById(selected).closedNeighborhood();
        c.elements().not(keep).addClass("faded");
      }
      c.nodes().filter((n) => hiddenLabels.has(n.data("kind"))).addClass("off");
      c.edges().filter((e) => hiddenTypes.has(e.data("type"))).addClass("off");
      if (hover) c.getElementById(hover).addClass("hover");
      c.nodes().unselect();
      if (selected) c.getElementById(selected).select();
    });
  }, [focus, dim, selected, hiddenLabels, hiddenTypes, hover, ready, nodes, edges]);

  const labelCounts = useMemo(() => {
    const m = new Map<string, number>();
    nodes.forEach((n) => m.set(n.label, (m.get(n.label) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [nodes]);
  const typeCounts = useMemo(() => {
    const ids = new Set(nodes.map((n) => n.id));
    const m = new Map<string, number>();
    edges.filter((e) => ids.has(e.source) && ids.has(e.target)).forEach((e) => m.set(e.type, (m.get(e.type) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [nodes, edges]);

  const toggle = (set: Set<string>, key: string, apply: (s: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key); else next.add(key);
    apply(next);
  };

  const zoomBy = (f: number) => {
    const c = cy.current;
    if (!c) return;
    c.zoom({ level: c.zoom() * f, renderedPosition: { x: c.width() / 2, y: c.height() / 2 } });
  };

  const find = () => {
    const c = cy.current;
    const q = query.trim().toLowerCase();
    if (!c || !q) return;
    const hit = c.nodes().filter((n) => n.id().toLowerCase().includes(q) || String(n.data("name")).toLowerCase().includes(q)).first();
    if (hit.nonempty()) { c.center(hit); onSelect(hit.id()); }
  };

  return (
    <div className="relative isolate h-full w-full overflow-hidden">
      {/* Cytoscape forces position:relative on its container and stacks its canvases inside it:
          keep that in layer 0, overlays in 10, tooltip in 20 */}
      <div ref={container} className="relative z-0 h-full w-full" data-testid="graph-canvas" />

      {/* search (top-left) */}
      <form onSubmit={(e) => { e.preventDefault(); find(); }}
            className="absolute left-3 top-3 z-10 flex items-center gap-1.5 rounded-md border border-line bg-panel px-2 py-1 shadow-sm">
        <Search size={14} className="text-ink-3" aria-hidden />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find node" aria-label="Find node"
               className="w-36 bg-transparent text-xs text-ink outline-none placeholder:text-ink-3" />
      </form>

      {/* labels and relationships (bottom-left) */}
      {(labelCounts.length > 0) && (
        <div className="absolute bottom-3 left-3 z-10 max-h-[calc(100%-5rem)] w-48 overflow-auto rounded-md border border-line bg-panel p-2 text-xs shadow-sm">
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Labels</p>
          {labelCounts.map(([label, n]) => (
            <button key={label} onClick={() => toggle(hiddenLabels, label, setHiddenLabels)} aria-pressed={!hiddenLabels.has(label)}
                    className={`flex w-full items-center gap-1.5 rounded px-1 py-0.5 hover:bg-raised ${hiddenLabels.has(label) ? "opacity-40" : ""}`}>
              <ShapeSwatch label={label} />
              <span className="flex-1 text-left text-ink-2">{label}</span>
              <span className="tabular-nums text-ink-3">{n}</span>
              {hiddenLabels.has(label) ? <EyeOff size={12} className="text-ink-3" /> : <Eye size={12} className="text-ink-3" />}
            </button>
          ))}
          {typeCounts.length > 0 && <p className="mb-1 mt-2 text-[11px] font-semibold uppercase tracking-wide text-ink-3">Relationships</p>}
          {typeCounts.map(([type, n]) => (
            <button key={type} onClick={() => toggle(hiddenTypes, type, setHiddenTypes)} aria-pressed={!hiddenTypes.has(type)}
                    className={`flex w-full items-center gap-1.5 rounded px-1 py-0.5 hover:bg-raised ${hiddenTypes.has(type) ? "opacity-40" : ""}`}>
              <span className="h-px w-3 bg-ink-3" aria-hidden />
              <span className="flex-1 truncate text-left font-mono text-[11px] text-ink-2">{type}</span>
              <span className="tabular-nums text-ink-3">{n}</span>
            </button>
          ))}
        </div>
      )}

      {/* controls (vertical, bottom-right): narrow enough to sit beside the legend on any canvas width */}
      <div className="absolute bottom-3 right-3 z-10 flex flex-col items-center gap-0.5 rounded-md border border-line bg-panel p-1 shadow-sm">
        <IconButton label="Zoom in" onClick={() => zoomBy(1.25)}><ZoomIn size={16} /></IconButton>
        <IconButton label="Zoom out" onClick={() => zoomBy(0.8)}><ZoomOut size={16} /></IconButton>
        <IconButton label="Fit (f)" onClick={() => fitCapped(cy.current)}><Maximize size={16} /></IconButton>
        <span className="my-0.5 h-px w-5 bg-line" aria-hidden />
        <div role="radiogroup" aria-label="Layout" className="flex flex-col gap-0.5">
          {([["force", "Force layout", Share2], ["tree", "Tree layout", Network], ["radial", "Radial layout", Orbit]] as const).map(([l, label, Icon]) => (
            <button key={l} role="radio" aria-checked={layout === l} title={label} aria-label={label} onClick={() => onLayout(l)}
                    className={`grid h-8 w-8 place-items-center rounded-md ${layout === l ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-raised"}`}>
              <Icon size={16} />
            </button>
          ))}
        </div>
        <span className="my-0.5 h-px w-5 bg-line" aria-hidden />
        <IconButton label="Dim (d)" active={dim} onClick={() => setDim((v) => !v)}><SunDim size={16} /></IconButton>
      </div>

      {tip && (
        <div className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full rounded-md border border-line bg-panel px-2 py-1 text-xs shadow-md"
             style={{ left: tip.x, top: tip.y - 16 }}>
          <p className="font-medium text-ink">{tip.name}</p>
          <p className="font-mono text-[11px] text-ink-3">{tip.label} · {tip.id}</p>
        </div>
      )}
    </div>
  );
}
