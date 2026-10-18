"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Core, ElementDefinition, LayoutOptions, NodeSingular } from "cytoscape";
import { ArrowRight, Boxes, ChevronDown, ChevronUp, ChevronsDownUp, Eye, EyeOff, Maximize, Network, Orbit, Search, Share2, SunDim, X, ZoomIn, ZoomOut } from "./icons";
import type { GraphEdge, GraphNode } from "@/lib/api";
import { styleOf } from "@/lib/entities";
import { IconButton, ShapeSwatch } from "./ui";

export type LayoutName = "force" | "tree" | "radial";
export type Compare = "both" | "before" | "after"; // a knowledge change on the canvas: show the old state, the new, or both

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
  onExpand?: (id: string) => void; // double-click a node: add its neighbours
  compare?: Compare;
}

export const edgeKey = (e: GraphEdge) => `${e.type}:${e.source}->${e.target}`;

const STYLE = [
  { selector: "node", style: {
      "background-color": "data(colour)", shape: "data(shape)", label: "data(label)", width: 22, height: 22,
      "font-size": 11, color: "#c9ccc0", "min-zoomed-font-size": 8, "text-valign": "bottom", "text-margin-y": 4,
      "text-wrap": "ellipsis", "text-max-width": "120px", "border-width": 0 } },
  { selector: "node.root", style: { width: 30, height: 30, "border-width": 3, "border-color": "#f1f1ec", "font-weight": 600, "font-size": 11 } },
  { selector: "node:selected", style: { "border-width": 3, "border-color": "#ff1053", "overlay-opacity": 0 } },
  { selector: "node.hover", style: { "border-width": 3, "border-color": "#ff1053", width: 30, height: 30, "z-index": 20 } },
  { selector: "edge", style: {
      width: 1.5, "line-color": "#5f6450", "target-arrow-color": "#5f6450", "target-arrow-shape": "triangle",
      "curve-style": "bezier", "arrow-scale": 0.8, label: "data(label)", "font-size": 10, "font-family": "IBM Plex Mono, monospace", color: "#939980",
      "min-zoomed-font-size": 7, "text-background-color": "#151613", "text-background-opacity": 0.9,
      "text-background-padding": "1px" } },
  { selector: "edge.overview", style: { label: "", width: 1, "line-color": "#2f3228", "target-arrow-color": "#2f3228" } },
  { selector: "edge.old", style: { "line-style": "dashed", "line-color": "#f2c14e", "target-arrow-color": "#f2c14e", color: "#f2c14e" } },
  // team grouping (overview): a team is a box around the services it owns; collapsed it is one node
  { selector: "node:parent", style: {
      shape: "rectangle", "background-color": "#f1f1ec", "background-opacity": 0.02, "border-width": 1,
      "border-color": "#3b3e34", padding: "14px", label: "data(label)", "text-valign": "top",
      "text-halign": "left", "text-margin-y": -4, "font-size": 12, "font-weight": 600, color: "#c9ccc0" } },
  { selector: "node.unowned", style: { "border-style": "dashed", "border-color": "#f2c14e",
      "background-opacity": 0, color: "#f2c14e" } },
  { selector: "node.collapsed", style: { width: 40, height: 40, "font-weight": 600, color: "#c9ccc0" } },
  { selector: "edge.meta", style: { width: "mapData(count, 1, 12, 1.5, 6)", "line-color": "#5f6450", "target-arrow-color": "#5f6450" } },
  { selector: "edge.asof", style: { "line-style": "solid", "line-color": "#5f6450", "target-arrow-color": "#5f6450", color: "#939980", label: "data(type)" } },
  { selector: "edge.quiet", style: { label: "" } },
  { selector: "edge.quiet.lit", style: { label: "data(label)" } },
  // following a line: hovering a node lights its lines; hovering or clicking a line lights it and names it
  { selector: "edge.flow", style: { width: 2.5, "line-color": "#ff1053", "target-arrow-color": "#ff1053", "z-index": 90 } },
  { selector: "edge.hot", style: { width: 3, "line-color": "#ff1053", "target-arrow-color": "#ff1053", "arrow-scale": 1,
      label: "data(label)", color: "#f1f1ec", "z-index": 99 } },
  { selector: "edge.pinned", style: { width: 3.5, "line-color": "#ff1053", "target-arrow-color": "#ff1053", "arrow-scale": 1.1,
      label: "data(label)", color: "#f1f1ec", "font-size": 11, "z-index": 100 } },
  { selector: "node.end", style: { "border-width": 3, "border-color": "#ff1053", "font-weight": 600, "z-index": 100 } },
  { selector: ".faded", style: { opacity: 0.12, "text-opacity": 0 } },
  { selector: ".off", style: { display: "none" } },
];

function layoutOptions(name: LayoutName, cy: Core, roots: string[], count: number, grouped = false): LayoutOptions {
  if (grouped && name === "force") return { name: "preset", padding: 40, animate: false } as LayoutOptions;
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
           nodeRepulsion: () => (count > 30 ? 9000 : 8000), idealEdgeLength: () => (count > 30 ? 90 : 120),
           nodeSeparation: 60 } as LayoutOptions;
}

const UNOWNED = "group:unowned"; // synthetic box, not a graph node

/** Cytoscape elements for the graph. Grouped (overview only): OWNS edges become nesting, a collapsed team hides its
    services and their DEPENDS_ON edges are redrawn to the team as combined edges with a count. */
function buildElements(nodes: GraphNode[], edges: GraphEdge[], roots: string[], overview: boolean, grouped: boolean,
                       collapsed: Set<string>): ElementDefinition[] {
  const ids = new Set(nodes.map((n) => n.id));
  const rootIds = new Set(roots);
  const node = (n: GraphNode, extra: Record<string, unknown> = {}, classes = "") => ({
    data: { id: n.id, name: n.name, label: n.name, kind: n.label, colour: styleOf(n.label).colour, shape: styleOf(n.label).shape, ...extra },
    classes: [rootIds.has(n.id) ? "root" : "", classes].join(" ").trim(),
  });
  const shown = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  if (!grouped) {
    return [
      ...nodes.map((n) => node(n)),
      ...shown.map((e) => ({
        data: { id: edgeKey(e), source: e.source, target: e.target, type: e.type, superseded: e.superseded ? 1 : 0,
                label: e.superseded || e.stale ? `${e.type} · ${e.superseded ? "superseded" : "stale"}` : e.type },
        classes: [e.superseded || e.stale ? "old" : "", overview ? "overview" : ""].join(" ").trim(),
      })),
    ];
  }
  const parentOf = new Map<string, string>();
  shown.filter((e) => e.type === "OWNS").forEach((e) => parentOf.set(e.target, e.source));
  const children = new Map<string, number>();
  parentOf.forEach((team) => children.set(team, (children.get(team) ?? 0) + 1));
  const rep = (id: string) => (collapsed.has(parentOf.get(id) ?? "") ? parentOf.get(id)! : id);
  // deterministic grid (force-directed boxes overlap when teams depend on each other): one cell per team, its
  // services in a small grid inside; services without an owner get their own row, outside every box
  const teams = nodes.filter((n) => n.label === "Team").sort((a, b) => a.name.localeCompare(b.name));
  const members = new Map<string, GraphNode[]>(teams.map((t) => [t.id, []]));
  const loose: GraphNode[] = [];
  nodes.filter((n) => n.label !== "Team").sort((a, b) => a.name.localeCompare(b.name))
    .forEach((n) => { const t = parentOf.get(n.id); if (t && members.has(t)) members.get(t)!.push(n); else loose.push(n); });
  const maxMembers = Math.max(1, ...[...members.values()].map((m) => m.length));
  const inner = Math.ceil(Math.sqrt(maxMembers));
  const [dx, dy] = [120, 85];
  const [cellW, cellH] = [inner * dx + 90, Math.ceil(maxMembers / inner) * dy + 90];
  // services without an owner get the first cell, in a dashed "No owner" box (the orphans of scenario 3)
  const cells: string[] = [...(loose.length ? [UNOWNED] : []), ...teams.map((t) => t.id)];
  if (loose.length) members.set(UNOWNED, loose);
  const perRow = Math.max(1, Math.ceil(Math.sqrt(cells.length)));
  const pos = new Map<string, { x: number; y: number }>();
  cells.forEach((cell, i) => {
    const [cx, cy] = [(i % perRow) * cellW, Math.floor(i / perRow) * cellH];
    pos.set(cell, { x: cx + cellW / 2 - 45, y: cy + cellH / 2 - 45 });
    members.get(cell)!.forEach((m, k) => pos.set(m.id, { x: cx + (k % inner) * dx, y: cy + Math.floor(k / inner) * dy }));
  });

  const els: ElementDefinition[] = [];
  if (loose.length) els.push({ data: { id: UNOWNED, name: "No owner", label: "No owner", kind: "Group" }, classes: "unowned" });
  for (const n of nodes) {
    const team = parentOf.get(n.id);
    if (team && collapsed.has(team)) continue;
    if (n.label === "Team" && collapsed.has(n.id)) els.push({ ...node(n, { label: `${n.name} · ${children.get(n.id) ?? 0}` }, "collapsed"), position: pos.get(n.id) });
    else if (n.label === "Team" && (children.get(n.id) ?? 0) > 0) els.push(node(n)); // a box: positioned by its services
    else els.push({ ...node(n, team ? { parent: team } : n.label !== "Team" ? { parent: UNOWNED } : {}), position: pos.get(n.id) });
  }
  const combined = new Map<string, { source: string; target: string; count: number; meta: boolean }>();
  for (const e of shown) {
    if (e.type === "OWNS") continue;
    const source = rep(e.source), target = rep(e.target);
    if (source === target) continue;
    const key = `${e.type}:${source}->${target}`;
    const c = combined.get(key) ?? { source, target, count: 0, meta: false };
    c.count += 1;
    c.meta ||= source !== e.source || target !== e.target;
    combined.set(key, c);
  }
  combined.forEach((c, key) => els.push({
    data: { id: key, source: c.source, target: c.target, type: key.slice(0, key.indexOf(":")), label: "", count: c.count },
    classes: c.meta ? "overview meta" : "overview",
  }));
  return els;
}

/** Busy graphs: edge labels only on the selected node's edges (they would otherwise pile up on each other). */
function quietLabels(c: Core) {
  c.edges().toggleClass("quiet", c.edges().length > 20);
}

/** Fit the graph, but never blow a small evidence graph up past 125%. */
function fitCapped(c: Core | null) {
  if (!c || !c.elements().length) return;
  c.fit(undefined, 64); // room for the legend and toolbar overlays
  if (c.zoom() > 1.25) { c.zoom(1.25); c.center(); }
}

export default function GraphCanvas({ nodes, edges, focus, hover, roots, layout, onLayout, selected, onSelect, onExpand, compare = "both" }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [ready, setReady] = useState(false);
  const [dim, setDim] = useState(false);
  const [pinned, setPinned] = useState<{ id: string; type: string; from: string; to: string } | null>(null);
  const [hiddenLabels, setHiddenLabels] = useState<Set<string>>(new Set());
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [grouped, setGrouped] = useState(true);
  const [legendOpen, setLegendOpen] = useState(true);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [tip, setTip] = useState<{ x: number; y: number; name: string; label: string; id: string } | null>(null);
  const handlers = useRef({ onSelect, onExpand });
  useEffect(() => { handlers.current = { onSelect, onExpand }; }, [onSelect, onExpand]);
  const wasGrouped = useRef(false);
  const relayout = useRef<() => void>(() => {}); // laid out while hidden (zero size): redo it when shown

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
      // node labels in the app's text face (next/font gives it a generated family name, read from the CSS variable)
      const face = getComputedStyle(document.documentElement).getPropertyValue("--font-heros").trim();
      if (face) cy.current.style().selector("node").style("font-family", face).update();
      cy.current.on("tap", "node", (e) => { if (!e.target.id().startsWith("group:")) handlers.current.onSelect(e.target.id()); });
      cy.current.on("tap", (e) => { if (e.target === cy.current) { handlers.current.onSelect(null); setPinned(null); } });
      cy.current.on("tap", "edge", (e) => {
        const ed = e.target;
        setPinned((cur) => (cur?.id === ed.id() ? null : {
          id: ed.id(), type: ed.data("type"), from: ed.source().data("name"), to: ed.target().data("name") }));
      });
      cy.current.on("mouseover", "node", (e) => {
        if (e.target.id().startsWith("group:")) return;
        const p = e.target.renderedPosition();
        setTip({ x: p.x, y: p.y, name: e.target.data("name"), label: e.target.data("kind"), id: e.target.id() });
      });
      cy.current.on("mouseout", "node", () => setTip(null));
      cy.current.on("mouseover", "node", (e) => e.target.connectedEdges().addClass("flow"));
      cy.current.on("mouseout", "node", (e) => e.target.connectedEdges().removeClass("flow"));
      cy.current.on("mouseover", "edge", (e) => e.target.addClass("hot"));
      cy.current.on("mouseout", "edge", (e) => e.target.removeClass("hot"));
      cy.current.on("dbltap", "node", (e) => {
        if (e.target.id().startsWith("group:")) return;
        if (e.target.data("kind") !== "Team" || !e.target.isParent() && !e.target.hasClass("collapsed")) {
          handlers.current.onExpand?.(e.target.id());
          return;
        }
        const id = e.target.id();
        setCollapsed((cur) => { const next = new Set(cur); if (next.has(id)) next.delete(id); else next.add(id); return next; });
      });
      cy.current.on("viewport", () => setTip(null));
      // the right panel opening or closing changes the canvas size: re-measure and re-fit
      let lastWidth = container.current.clientWidth;
      const ro = new ResizeObserver(() => {
        const w = container.current?.clientWidth ?? 0;
        cy.current?.resize();
        if (lastWidth === 0 && w > 0) relayout.current(); else fitCapped(cy.current);
        lastWidth = w;
      });
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
      if (e.key === "Escape") setPinned(null);
      if (e.key === "f") fitCapped(cy.current);
      if (e.key === "d") setDim((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const overview = useMemo(() => !roots.length && edges.every((e) => e.type === "DEPENDS_ON" || e.type === "OWNS"), [roots, edges]);

  useEffect(() => { setPinned(null); }, [nodes, edges]); // eslint-disable-line react-hooks/set-state-in-effect

  // team grouping applies to the overview only, and not while Team is filtered out
  const groupedNow = overview && grouped && !hiddenLabels.has("Team");

  // new elements: replace and lay out (instance kept)
  useEffect(() => {
    const c = cy.current;
    if (!c || !ready) return;
    const els = buildElements(nodes, edges, roots, overview, groupedNow, collapsed);
    const before = c.nodes().map((n) => n.id());
    const ids = new Set(nodes.map((n) => n.id));
    const grows = before.length > 0 && !groupedNow && !wasGrouped.current && before.every((id) => ids.has(id));
    wasGrouped.current = groupedNow;
    if (grows) {
      // expansion: keep what is on screen where it is, place only the new nodes around it
      const added = els.filter((el) => c.getElementById(String(el.data.id)).empty());
      if (!added.length) return;
      const fixed = c.nodes().map((n) => ({ nodeId: n.id(), position: { ...n.position() } }));
      c.batch(() => {
        added.forEach((el) => {
          if (el.data.source) return;
          const link = added.find((e) => e.data.source && (e.data.source === el.data.id || e.data.target === el.data.id));
          const anchor = link ? c.getElementById(String(link.data.source === el.data.id ? link.data.target : link.data.source)) : null;
          const p = anchor?.nonempty() ? anchor.position() : { x: 0, y: 0 };
          el.position = { x: p.x + (Math.random() - 0.5) * 80, y: p.y + (Math.random() - 0.5) * 80 };
        });
        c.add(added.filter((el) => !el.data.source));
        c.add(added.filter((el) => el.data.source));
      });
      c.layout({ name: "fcose", animate: false, randomize: false, padding: 40, fixedNodeConstraint: fixed,
                 nodeRepulsion: () => 40000, idealEdgeLength: () => 160, nodeSeparation: 110 } as LayoutOptions).run();
      quietLabels(c);
      fitCapped(c);
      return;
    }
    c.batch(() => { c.elements().remove(); c.add(els); });
    c.layout(layoutOptions(layout, c, roots, nodes.length, groupedNow)).run();
    quietLabels(c);
    fitCapped(c);
  }, [nodes, edges, roots, ready, overview, groupedNow, collapsed]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    relayout.current = () => {
      const c = cy.current;
      if (!c || !c.nodes().length) return;
      c.layout(layoutOptions(layout, c, roots, c.nodes().length, groupedNow)).run();
      fitCapped(c);
    };
  });

  // layout switch only
  useEffect(() => {
    const c = cy.current;
    if (!c || !ready || !c.nodes().length) return;
    c.layout(layoutOptions(layout, c, roots, c.nodes().length, groupedNow)).run();
    fitCapped(c);
  }, [layout]); // eslint-disable-line react-hooks/exhaustive-deps

  // classes: focus (one step), dim (selection neighbourhood), filters, hover, selection
  useEffect(() => {
    const c = cy.current;
    if (!c || !ready) return;
    c.batch(() => {
      c.elements().removeClass("faded off hover asof pinned end");
      if (compare !== "both") {
        // ended edges and the current edges that replaced them (same type, same target)
        const ended = c.edges("[superseded = 1]");
        const replaced = c.edges("[superseded != 1]").filter((e) =>
          ended.some((o) => o.data("type") === e.data("type") && o.data("target") === e.data("target")));
        if (compare === "before") { replaced.addClass("off"); ended.addClass("asof"); } else ended.addClass("off");
        c.nodes().filter((n) => n.connectedEdges().length > 0 && n.connectedEdges().filter((e) => !e.hasClass("off")).empty()).addClass("faded");
      }
      if (focus) c.elements().filter((el) => !focus.has(el.id())).addClass("faded");
      if (dim && selected) {
        const keep = c.getElementById(selected).closedNeighborhood();
        c.elements().not(keep).addClass("faded");
      }
      c.nodes().filter((n) => hiddenLabels.has(n.data("kind"))).addClass("off");
      c.edges().filter((e) => hiddenTypes.has(e.data("type"))).addClass("off");
      if (pinned) {
        const line = c.getElementById(pinned.id);
        if (line.nonempty()) {
          const ends = line.connectedNodes();
          c.elements().not(line.union(ends).union(ends.ancestors())).addClass("faded");
          line.addClass("pinned");
          ends.addClass("end");
        }
      }
      if (hover) c.getElementById(hover).addClass("hover");
      c.nodes().unselect();
      c.edges().removeClass("lit");
      if (selected) {
        const sel = c.getElementById(selected).select();
        if (sel.connectedEdges().length <= 10) sel.connectedEdges().addClass("lit"); // a hub's labels would pile up again
      }
    });
  }, [focus, dim, selected, hiddenLabels, hiddenTypes, hover, ready, nodes, edges, compare, pinned]);

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
      <div ref={container} className="relative z-0 h-full w-full bg-[#03040a]" data-testid="graph-canvas" />

      {/* search (top-left) */}
      <form onSubmit={(e) => { e.preventDefault(); find(); }}
            className="absolute left-3 top-3 z-10 flex items-center gap-1.5 rounded border border-line bg-panel px-2 py-1 focus-within:border-accent">
        <Search size={14} className="text-ink-3" aria-hidden />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find node" aria-label="Find node"
               className="w-36 bg-transparent text-xs text-ink outline-none placeholder:text-ink-3 focus-visible:outline-none" />
      </form>

      {pinned && (
        <div className="absolute left-3 top-14 z-10 flex max-w-[calc(100%-5rem)] items-center gap-2 rounded border border-accent bg-panel px-2 py-1 text-xs">
          <span className="truncate text-ink">{pinned.from}</span>
          <span className="inline-flex shrink-0 items-center gap-1 font-mono text-[11px] text-accent-ink">{pinned.type}<ArrowRight size={11} aria-hidden /></span>
          <span className="truncate text-ink">{pinned.to}</span>
          <button onClick={() => setPinned(null)} aria-label="Clear highlighted line" title="Clear (Esc)"
                  className="ml-1 shrink-0 text-ink-3 hover:text-ink"><X size={13} /></button>
        </div>
      )}

      {/* labels and relationships (bottom-left) */}
      {(labelCounts.length > 0) && (
        <div className="absolute bottom-3 left-3 z-10 max-h-[calc(100%-5rem)] w-48 overflow-auto rounded border border-line bg-panel p-2 text-xs">
          <button onClick={() => setLegendOpen((v) => !v)} aria-expanded={legendOpen}
                  className="mb-1 flex w-full items-center justify-between text-xs font-medium text-ink-2 hover:text-ink">
            Labels{legendOpen ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
          </button>
          {legendOpen && labelCounts.map(([label, n]) => (
            <button key={label} onClick={() => toggle(hiddenLabels, label, setHiddenLabels)} aria-pressed={!hiddenLabels.has(label)}
                    className={`flex w-full items-center gap-1.5 rounded px-1 py-0.5 hover:bg-raised ${hiddenLabels.has(label) ? "opacity-40" : ""}`}>
              <ShapeSwatch label={label} />
              <span className="flex-1 text-left text-ink-2">{label}</span>
              <span className="tabular-nums text-ink-3">{n}</span>
              {hiddenLabels.has(label) ? <EyeOff size={12} className="text-ink-3" /> : <Eye size={12} className="text-ink-3" />}
            </button>
          ))}
          {legendOpen && typeCounts.length > 0 && <p className="mb-1 mt-2 text-xs font-medium text-ink-2">Relationships</p>}
          {legendOpen && typeCounts.map(([type, n]) => (
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
      <div className="absolute bottom-3 right-3 z-10 flex flex-col items-center gap-0.5 rounded border border-line bg-panel p-1">
        <IconButton label="Zoom in" onClick={() => zoomBy(1.25)}><ZoomIn size={16} /></IconButton>
        <IconButton label="Zoom out" onClick={() => zoomBy(0.8)}><ZoomOut size={16} /></IconButton>
        <IconButton label="Fit (f)" onClick={() => fitCapped(cy.current)}><Maximize size={16} /></IconButton>
        <span className="my-0.5 h-px w-5 bg-line" aria-hidden />
        <div role="radiogroup" aria-label="Layout" className="flex flex-col gap-0.5">
          {([["force", "Force layout", Share2], ["tree", "Tree layout", Network], ["radial", "Radial layout", Orbit]] as const).map(([l, label, Icon]) => (
            <button key={l} role="radio" aria-checked={layout === l} title={label} aria-label={label} onClick={() => onLayout(l)}
                    className={`grid h-8 w-8 place-items-center rounded ${layout === l ? "bg-accent-soft text-accent-ink" : "text-ink-2 hover:bg-raised"}`}>
              <Icon size={16} />
            </button>
          ))}
        </div>
        <span className="my-0.5 h-px w-5 bg-line" aria-hidden />
        {overview && (
          <>
            <IconButton label="Group by team" active={grouped} onClick={() => setGrouped((v) => !v)}><Boxes size={16} /></IconButton>
            {grouped && (
              <IconButton label={collapsed.size ? "Expand all teams" : "Collapse all teams"} active={collapsed.size > 0}
                          onClick={() => setCollapsed(collapsed.size ? new Set() : new Set(nodes.filter((n) => n.label === "Team").map((n) => n.id)))}>
                <ChevronsDownUp size={16} />
              </IconButton>
            )}
            <span className="my-0.5 h-px w-5 bg-line" aria-hidden />
          </>
        )}
        <IconButton label="Dim (d)" active={dim} onClick={() => setDim((v) => !v)}><SunDim size={16} /></IconButton>
      </div>

      {tip && (
        <div className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full rounded border border-line bg-panel px-2 py-1 text-xs"
             style={{ left: tip.x, top: tip.y - 16 }}>
          <p className="font-medium text-ink">{tip.name}</p>
          <p className="font-mono text-[11px] text-ink-3">{tip.label} · {tip.id}</p>
        </div>
      )}
    </div>
  );
}
