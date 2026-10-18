"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ForceGraph3DInstance } from "3d-force-graph";
import type { Group, Mesh, MeshLambertMaterial, Object3D } from "three";
import type SpriteTextType from "three-spritetext";
import { ArrowRight, ChevronDown, ChevronUp, Eye, EyeOff, Maximize, Network, Orbit, RotateCcw, Search, Share2, SunDim, X, ZoomIn, ZoomOut } from "./icons";
import type { GraphEdge, GraphNode } from "@/lib/api";
import { styleOf, type Shape } from "@/lib/entities";
import { edgeKey, type Compare, type LayoutName } from "./GraphCanvas";
import { IconButton, ShapeSwatch } from "./ui";

/* The graph in 3D (3d-force-graph on three.js). Kept readable rather than spectacular:
   orbit controls (up stays up), a collision force so nodes never overlap, depth fog so far nodes recede,
   camera-facing labels shown only where they fit, team clusters in the overview, and the same line-following
   as the 2D canvas (hover a node or line to light it, click a line to pin it; lit lines carry flow particles). */

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  focus: Set<string> | null;
  hover: string | null;
  roots: string[];
  layout: LayoutName;
  onLayout: (l: LayoutName) => void;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onExpand?: (id: string) => void;
  compare?: Compare;
  spotlight?: Set<string> | null; // node ids + edge keys from the tools' paths: open their teams, light them, fly to them
  onUnavailable?: () => void; // no WebGL here: the page falls back to 2D
}

type N = { id: string; name: string; kind: string; team?: string; x?: number; y?: number; z?: number };
type L = { id: string; source: string | N; target: string | N; type: string; old: boolean; superseded: boolean };
type Parts = { group: Group; mesh: Mesh; label: SpriteTextType };

const ACCENT = "#ff1053";
const INK = "#ffffff";
const PAGE = "#03040a"; // deep space
const LINK = "#9fb4ff"; // bright periwinkle on black
const LINK_FAINT = "#3a4470"; // dimmed lines stay visible
const OWNS_LINK = "#5ec2b7"; // team ownership in teal
const OLD = "#f2c14e";
const LABEL_LIMIT = 30;
const MEMORY = new Set(["Episode", "Lesson", "Procedure", "Message", "Conversation"]); // above this many nodes, only some labels are drawn

const idOf = (end: string | N) => (typeof end === "string" ? end : end.id);

/** One solid per node shape, sized so the types read at a glance. */
async function makeMesh(shape: Shape, colour: string): Promise<Mesh> {
  const T = await import("three");
  const geometry = {
    "round-rectangle": () => new T.BoxGeometry(7, 5, 5),
    ellipse: () => new T.SphereGeometry(3.6, 20, 14),
    hexagon: () => new T.CylinderGeometry(5, 5, 3.2, 6),
    tag: () => new T.ConeGeometry(3.4, 6.5, 4),
    triangle: () => new T.TetrahedronGeometry(5),
    diamond: () => new T.OctahedronGeometry(4.4),
    rectangle: () => new T.BoxGeometry(4.6, 5.8, 1.3),
    octagon: () => new T.DodecahedronGeometry(3.6),
    "round-tag": () => new T.TorusGeometry(3, 1.2, 10, 20),
  }[shape]();
  return new T.Mesh(geometry, new T.MeshLambertMaterial({ color: colour, transparent: true, opacity: 1, emissive: "#000000" }));
}

// fog from the current camera distance: near things crisp, far things recede into the page colour
async function applyFog(g: ForceGraph3DInstance<N, L>) {
  const T = await import("three");
  const cam = g.cameraPosition();
  const target = (g.controls() as { target?: { x: number; y: number; z: number } }).target ?? { x: 0, y: 0, z: 0 };
  const d = Math.hypot(cam.x - target.x, cam.y - target.y, cam.z - target.z) || 300;
  g.scene().fog = new T.Fog(PAGE, d * 0.95, d * 3.2);
}

/** Move the camera towards its target by a factor (0.8 = 20% closer). */
function closer(g: ForceGraph3DInstance<N, L>, f: number) {
  const c = g.cameraPosition();
  const t = (g.controls() as { target?: { x: number; y: number; z: number } }).target ?? { x: 0, y: 0, z: 0 };
  g.cameraPosition({ x: t.x + (c.x - t.x) * f, y: t.y + (c.y - t.y) * f, z: t.z + (c.z - t.z) * f }, t, 300);
}

/** A stable small number per id, so each line keeps its own bend between renders. */
function hashOf(id: string) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h;
}

export default function Graph3D({ nodes: rawNodes, edges: rawEdges, focus, hover, roots, layout, onLayout, selected, onSelect, onExpand, compare = "both", onUnavailable, spotlight = null }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const fg = useRef<ForceGraph3DInstance<N, L> | null>(null);
  const parts = useRef(new Map<string, Parts>());
  const cache = useRef(new Map<string, N>()); // node objects keep their positions across updates
  const fitNext = useRef(true);
  const refitOnce = useRef(false);
  const spotlightRef = useRef<Set<string> | null>(null);
  const revealRef = useRef<Set<string> | null>(null); // a click just revealed these: frame them
  const selectedRef = useRef<string | null>(null);
  useEffect(() => { selectedRef.current = selected; }, [selected]);
  useEffect(() => { spotlightRef.current = spotlight; if (spotlight?.size) refitOnce.current = true; }, [spotlight]);
  const lastClick = useRef<{ id: string; t: number; timer?: ReturnType<typeof setTimeout> } | null>(null);
  const handlers = useRef({ onSelect, onExpand });
  useEffect(() => { handlers.current = { onSelect, onExpand }; }, [onSelect, onExpand]);

  const [ready, setReady] = useState(false);
  const [built, setBuilt] = useState(0); // meshes exist: the visual pass has something to style
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [hoverLink, setHoverLink] = useState<string | null>(null);
  const [pinned, setPinned] = useState<{ id: string; type: string; from: string; to: string } | null>(null);
  const [dim, setDim] = useState(true); // click a node: it and its neighbours stay, the rest fades
  const [legendOpen, setLegendOpen] = useState(true);
  const [hiddenLabels, setHiddenLabels] = useState<Set<string>>(new Set());
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");

  const overview = useMemo(() => rawNodes.some((n) => n.label === "Team") && rawEdges.some((e) => e.type === "OWNS"), [rawNodes, rawEdges]);

  // overview starts at team level: a closed team is one node with its service count, and the dependencies of its
  // services become one line per team pair (thicker the more there are). Double-click a team to open it.
  const [openTeams, setOpenTeams] = useState<Set<string>>(new Set());
  useEffect(() => { setOpenTeams(new Set()); }, [rawNodes]); // eslint-disable-line react-hooks/set-state-in-effect
  const { nodes, edges, lineCount } = useMemo(() => {
    const lineCount = new Map<string, number>();
    if (!overview) return { nodes: rawNodes, edges: rawEdges, lineCount };
    const teamOf = new Map<string, string>();
    rawEdges.filter((e) => e.type === "OWNS").forEach((e) => teamOf.set(e.target, e.source));
    const size = new Map<string, number>();
    teamOf.forEach((t) => size.set(t, (size.get(t) ?? 0) + 1));
    // teams holding anything the answer is about open on their own
    const autoOpen = new Set<string>();
    spotlight?.forEach((id) => { const t = teamOf.get(id); if (t) autoOpen.add(t); });
    const isOpen = (t: string) => openTeams.has(t) || autoOpen.has(t);
    const closed = (svc: string) => { const t = teamOf.get(svc); return t !== undefined && !isOpen(t); };
    const rep = (id: string) => (closed(id) ? teamOf.get(id)! : id);
    const nodes = rawNodes.filter((n) => !closed(n.id))
      .map((n) => (n.label === "Team" ? { ...n, name: `${n.name} · ${size.get(n.id) ?? 0}` } : n));
    const merged = new Map<string, GraphEdge>();
    for (const e of rawEdges) {
      if (e.type === "OWNS") { if (isOpen(e.source)) merged.set(edgeKey(e), e); continue; }
      const source = rep(e.source), target = rep(e.target);
      if (source === target) continue;
      const m = { ...e, source, target };
      const k = edgeKey(m);
      lineCount.set(k, (lineCount.get(k) ?? 0) + 1);
      merged.set(k, m);
    }
    return { nodes, edges: [...merged.values()], lineCount };
  }, [overview, rawNodes, rawEdges, openTeams, spotlight]);

  const toggleTeam = useRef<(id: string) => boolean>(() => false);
  useEffect(() => {
    toggleTeam.current = (id) => {
      if (!overview || !rawNodes.some((n) => n.id === id && n.label === "Team")) return false;
      refitOnce.current = true; // opening or closing a team re-frames the view
      setOpenTeams((cur) => { const next = new Set(cur); if (next.has(id)) next.delete(id); else next.add(id); return next; });
      return true;
    };
  });

  // ------------------------------------------------------------------ one instance for the page lifetime
  useEffect(() => {
    let disposed = false;
    let observer: ResizeObserver | null = null;
    (async () => {
      const ForceGraph3D = (await import("3d-force-graph")).default;
      const { forceCollide } = await import("d3-force-3d");
      if (disposed || !host.current) return;
      // WebGL can be missing (hardware acceleration off, remote desktop): say so and fall back instead of a blank canvas
      const probe = document.createElement("canvas");
      if (!(probe.getContext("webgl2") || probe.getContext("webgl"))) { onUnavailable?.(); return; }
      let g: ForceGraph3DInstance<N, L>;
      try {
        g = new ForceGraph3D(host.current, { controlType: "orbit" }) as unknown as ForceGraph3DInstance<N, L>;
      } catch { onUnavailable?.(); return; }
      g.backgroundColor(PAGE).showNavInfo(false).enableNodeDrag(false).linkOpacity(0.85)
        .nodeLabel(() => "") // our own labels; no browser tooltip on top of them
        .linkLabel((l: L) => l.type)
        .linkDirectionalArrowLength(5).linkDirectionalArrowRelPos(1)
        .linkCurvature(0.22).linkCurveRotation((l: L) => (hashOf(l.id) % 628) / 100)
        .linkDirectionalParticleWidth(1.8).linkDirectionalParticleSpeed(0.006)
        .warmupTicks(30).cooldownTicks(140)
        .onDagError(() => { /* a cycle: the tree layout places what it can, the rest stays force-directed */ })
        .onNodeHover((n: N | null) => { setHoverNode(n?.id ?? null); if (host.current) host.current.style.cursor = n ? "pointer" : ""; })
        .onLinkHover((l: L | null) => { setHoverLink(l?.id ?? null); if (host.current) host.current.style.cursor = l ? "pointer" : ""; })
        .onNodeClick((n: N) => {
          // a single click waits briefly: selecting opens the side panel, which resizes the canvas and would move the
          // node out from under the second click of a double-click
          if (lastClick.current?.id === n.id && lastClick.current.timer) {
            clearTimeout(lastClick.current.timer);
            lastClick.current = null;
            if (!toggleTeam.current(n.id)) handlers.current.onExpand?.(n.id);
            return;
          }
          if (lastClick.current?.timer) clearTimeout(lastClick.current.timer);
          const timer = setTimeout(() => {
            lastClick.current = null;
            handlers.current.onSelect(n.id);
            if (!toggleTeam.current(n.id)) handlers.current.onExpand?.(n.id); // reveal what is connected to it
          }, 260);
          lastClick.current = { id: n.id, t: Date.now(), timer };
        })
        .onLinkClick((l: L) => {
          const from = typeof l.source === "string" ? l.source : l.source.name;
          const to = typeof l.target === "string" ? l.target : l.target.name;
          setPinned((cur) => (cur?.id === l.id ? null : { id: l.id, type: l.type, from, to }));
        })
        .onBackgroundClick(() => { handlers.current.onSelect(null); setPinned(null); })
        .onEngineStop(() => {
          if (!fitNext.current) return;
          fitNext.current = false;
          const reveal = revealRef.current;
          revealRef.current = null;
          if (reveal && reveal.size) {
            // fly to the clicked node, close enough to read what just appeared around it
            const c = cache.current.get(selectedRef.current ?? "");
            if (c?.x !== undefined) {
              const len = Math.hypot(c.x, c.y ?? 0, c.z ?? 0) || 1, k = 1 + 420 / len; // close enough to read, far enough that labels keep their size
              g.cameraPosition({ x: c.x * k, y: (c.y ?? 0) * k, z: (c.z ?? 0) * k }, { x: c.x, y: c.y ?? 0, z: c.z ?? 0 }, 800);
              setTimeout(() => applyFog(g), 850);
              return;
            }
          }
          const spot = spotlightRef.current;
          if (spot && spot.size) { g.zoomToFit(700, 60, (n: N) => spot.has(n.id)); setTimeout(() => applyFog(g), 760); return; }
          g.zoomToFit(500, 12);
          setTimeout(() => { closer(g, 0.8); applyFog(g); }, 560);
        });
      g.d3Force("collide", forceCollide<N>(11) as never); // nodes never overlap
      // overview: every service is pulled towards its team, so teams read as separate clusters
      let clusterNodes: N[] = [];
      const cluster = Object.assign((alpha: number) => {
        const byId = new Map(clusterNodes.map((n) => [n.id, n]));
        for (const n of clusterNodes) {
          const t = n.team ? byId.get(n.team) : undefined;
          if (!t || t.x === undefined || n.x === undefined) continue;
          const k = alpha * 0.35;
          const v = n as N & { vx?: number; vy?: number; vz?: number };
          v.vx = (v.vx ?? 0) + (t.x - n.x) * k;
          v.vy = (v.vy ?? 0) + ((t.y ?? 0) - (n.y ?? 0)) * k;
          v.vz = (v.vz ?? 0) + ((t.z ?? 0) - (n.z ?? 0)) * k;
        }
      }, { initialize: (ns: N[]) => { clusterNodes = ns; } });
      g.d3Force("cluster", cluster as never);
      g.d3Force("charge")?.strength?.(-70);
      fg.current = g;
      (host.current as HTMLDivElement & { __graph?: unknown }).__graph = g; // for browser tests: screen positions of nodes
      const resize = () => { if (host.current) g.width(host.current.clientWidth).height(host.current.clientHeight); };
      observer = new ResizeObserver(resize);
      observer.observe(host.current);
      resize();
      setReady(true);
    })();
    return () => { disposed = true; observer?.disconnect(); fg.current?._destructor(); fg.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- one instance for the page lifetime

  // ------------------------------------------------------------------ data: reuse node objects, build meshes once
  useEffect(() => {
    const g = fg.current;
    if (!g || !ready) return;
    let cancelled = false;
    (async () => {
      const SpriteText = (await import("three-spritetext")).default;
      const face = getComputedStyle(document.documentElement).getPropertyValue("--font-heros").trim() || "Helvetica, Arial";
      const team = new Map<string, string>();
      edges.filter((e) => e.type === "OWNS").forEach((e) => team.set(e.target, e.source));
      const ids = new Set(nodes.map((n) => n.id));
      const before = new Set(cache.current.keys());
      const same = before.size === ids.size && [...before].every((id) => ids.has(id)); // a re-run with the same nodes
      const grows = !same && before.size > 0 && [...before].every((id) => ids.has(id));
      const next: N[] = nodes.map((n) => {
        const old = cache.current.get(n.id);
        if (old) { old.team = team.get(n.id); return old; }
        // a new node starts beside a neighbour already on screen, so expansion grows out of it
        const near = edges.find((e) => (e.source === n.id && before.has(e.target)) || (e.target === n.id && before.has(e.source)));
        const anchor = near ? cache.current.get(near.source === n.id ? near.target : near.source) : undefined;
        const jitter = () => (Math.random() - 0.5) * 30;
        return { id: n.id, name: n.name, kind: n.label, team: team.get(n.id),
                 ...(anchor?.x !== undefined ? { x: anchor.x + jitter(), y: (anchor.y ?? 0) + jitter(), z: (anchor.z ?? 0) + jitter() } : {}) };
      });
      cache.current = new Map(next.map((n) => [n.id, n]));
      for (const n of next) {
        if (parts.current.has(n.id)) continue;
        const { colour, shape } = styleOf(n.kind);
        const mesh = await makeMesh(shape, colour);
        if (cancelled) return;
        const label = new SpriteText(n.name.length > 26 ? `${n.name.slice(0, 25)}…` : n.name, 5.2, INK);
        label.fontFace = face;
        label.backgroundColor = "rgba(6,8,20,0.78)";
        label.borderColor = colour;
        label.borderWidth = 0.35;
        label.fontWeight = "bold";
        label.borderRadius = 2;
        label.padding = 1.6;
        label.position.set(0, 10, 0);
        const T = await import("three");
        const group = new T.Group();
        group.add(mesh, label);
        parts.current.set(n.id, { group, mesh, label });
      }
      const links: L[] = edges.filter((e) => ids.has(e.source) && ids.has(e.target))
        .map((e) => ({ id: edgeKey(e), source: e.source, target: e.target, type: e.type, old: Boolean(e.superseded || e.stale), superseded: Boolean(e.superseded) }));
      const refit = refitOnce.current;
      if (refit) fitNext.current = true; else if (!same) fitNext.current = !grows;
      if (grows && !refit) {
        // nodes appeared next to something already on screen: frame the old ones they attach to plus the new ones
        const fresh = next.filter((n) => !before.has(n.id)).map((n) => n.id);
        revealRef.current = new Set<string>([...fresh, ...(selectedRef.current ? [selectedRef.current] : [])]);
        fitNext.current = true;
      }
      refitOnce.current = false;
      g.nodeThreeObject((n: N) => parts.current.get(n.id)?.group as Object3D);
      // layout: tree and radial are 3D DAG layouts rooted at the queried node; force otherwise
      g.dagMode(layout === "tree" ? "td" : layout === "radial" ? "radialout" : (null as never)).dagLevelDistance(layout === "force" ? (null as never) : 60);
      // overview: OWNS pulls a service tight to its team, dependencies are long and weak, so teams form clusters
      type LinkForce = { distance: (f: (l: L) => number) => LinkForce; strength: (f: (l: L) => number) => LinkForce };
      const linkForce = g.d3Force("link") as unknown as LinkForce | undefined;
      if (linkForce) {
        // services far apart (dependencies), everything attached to a node (people, docs, deploys, incidents) close to it
        linkForce.distance((l) => (overview ? (l.type === "OWNS" ? 18 : l.type === "DEPENDS_ON" ? 95 : 60) : 45));
        linkForce.strength((l) => (overview ? (l.type === "OWNS" ? 0.9 : l.type === "DEPENDS_ON" ? 0.03 : 0.7) : 0.6));
      }
      // small graphs draw every label, so nodes keep a label's width apart; big ones only the solid's
      const collide = g.d3Force("collide") as unknown as { radius: (r: number) => unknown } | undefined;
      collide?.radius(next.length <= LABEL_LIMIT ? 34 : 20);
      g.graphData({ nodes: next, links });
      setBuilt((b) => b + 1);
      if (!grows || refit) g.d3ReheatSimulation(); // a new spotlight re-runs the settle, so the camera flies to it
    })();
    return () => { cancelled = true; };
  }, [nodes, edges, ready, overview]); // eslint-disable-line react-hooks/exhaustive-deps

  // layout switch only
  useEffect(() => {
    const g = fg.current;
    if (!g || !ready) return;
    fitNext.current = true;
    g.dagMode(layout === "tree" ? "td" : layout === "radial" ? "radialout" : (null as never)).dagLevelDistance(layout === "force" ? (null as never) : 45);
    g.d3ReheatSimulation();
  }, [layout, ready]);

  useEffect(() => { setPinned(null); }, [nodes, edges]); // eslint-disable-line react-hooks/set-state-in-effect

  // ------------------------------------------------------------------ what is lit, what fades
  const adjacency = useMemo(() => {
    const m = new Map<string, { nodes: Set<string>; links: Set<string> }>();
    const add = (a: string, b: string, k: string) => {
      const x = m.get(a) ?? { nodes: new Set<string>(), links: new Set<string>() };
      x.nodes.add(b); x.links.add(k); m.set(a, x);
    };
    edges.forEach((e) => { const k = edgeKey(e); add(e.source, e.target, k); add(e.target, e.source, k); });
    return m;
  }, [edges]);

  const state = useMemo(() => {
    const litNodes = new Set<string>(), litLinks = new Set<string>(), ends = new Set<string>();
    let faded: ((id: string) => boolean) | null = null;
    const lightNode = (id: string) => { litNodes.add(id); adjacency.get(id)?.links.forEach((k) => litLinks.add(k)); };
    spotlight?.forEach((id) => { if (id.includes("->")) litLinks.add(id); else litNodes.add(id); });
    if (hoverNode) lightNode(hoverNode);
    if (hover) litNodes.add(hover);
    if (selected) litNodes.add(selected);
    if (hoverLink) litLinks.add(hoverLink);
    if (pinned) {
      const e = edges.find((x) => edgeKey(x) === pinned.id);
      if (e) { litLinks.add(pinned.id); ends.add(e.source); ends.add(e.target); }
      faded = (id) => !(id === pinned.id || ends.has(id));
    } else if (focus) faded = (id) => !focus.has(id);
    else if (dim && selected) {
      const keep = new Set([selected, ...(adjacency.get(selected)?.nodes ?? [])]);
      const keepLinks = adjacency.get(selected)?.links ?? new Set<string>();
      faded = (id) => !(keep.has(id) || keepLinks.has(id));
    } else if (spotlight?.size) faded = (id) => !spotlight.has(id);
    // before/after a change: ended edges and the edges that replaced them (same type, same target)
    const ended = edges.filter((e) => e.superseded);
    const replaced = new Set(edges.filter((e) => !e.superseded && ended.some((o) => o.type === e.type && o.target === e.target)).map(edgeKey));
    const hiddenLinks = new Set<string>([
      ...edges.filter((e) => hiddenTypes.has(e.type)).map(edgeKey),
      ...(compare === "before" ? replaced : compare === "after" ? ended.map(edgeKey) : []),
    ]);
    return { litNodes, litLinks, ends, faded, hiddenLinks };
  }, [hoverNode, hoverLink, hover, selected, pinned, focus, dim, adjacency, edges, hiddenTypes, compare, spotlight]);

  // node visuals: no rebuild, only material and label changes
  useEffect(() => {
    const lots = nodes.length > LABEL_LIMIT;
    const rootSet = new Set(roots);
    const owned = new Set(edges.filter((e) => e.type === "OWNS").map((e) => e.target));
    parts.current.forEach((p, id) => {
      const n = cache.current.get(id);
      const material = p.mesh.material as MeshLambertMaterial;
      const lit = state.litNodes.has(id) || state.ends.has(id);
      const fade = state.faded ? state.faded(id) : false;
      material.opacity = fade ? 0.3 : 1; // dimmed, not removed
      // every node glows in its own colour; lit ones glow in the neon
      material.emissive.set(lit ? ACCENT : material.color);
      material.emissiveIntensity = lit ? 0.75 : 0.35;
      p.group.scale.setScalar(rootSet.has(id) ? 1.9 : lit ? 1.6 : 1.4);
      const orphan = overview && n?.kind === "Service" && !owned.has(id);
      const memory = MEMORY.has(n?.kind ?? ""); // ids, not names: labelled only when hovered or selected
      p.label.visible = !fade && (!lots || lit || rootSet.has(id) || n?.kind === "Team" || orphan ||
        (hoverNode !== null && (adjacency.get(hoverNode)?.nodes.has(id) ?? false)) ||
        (!memory && selected !== null && (adjacency.get(selected)?.nodes.has(id) ?? false))) && (!memory || lit || hoverNode === id); // the clicked node's neighbours
      p.label.color = orphan ? OLD : INK;
    });
  }, [state, nodes, edges, roots, overview, hoverNode, adjacency, built, selected]);

  // link visuals
  useEffect(() => {
    const g = fg.current;
    if (!g || !ready) return;
    const anyLit = state.litLinks.size > 0;
    g.nodeVisibility((n: N) => !hiddenLabels.has(n.kind))
      .linkVisibility((l: L) => !state.hiddenLinks.has(l.id) && !hiddenLabels.has(cache.current.get(idOf(l.source))?.kind ?? "") && !hiddenLabels.has(cache.current.get(idOf(l.target))?.kind ?? ""))
      .linkColor((l: L) => {
        if (state.litLinks.has(l.id)) return ACCENT;
        if (state.faded?.(l.id)) return LINK_FAINT;
        if (l.old && compare !== "before") return OLD;
        if (l.type === "OWNS" && overview) return OWNS_LINK;
        return anyLit ? LINK_FAINT : LINK;
      })
      .linkWidth((l: L) => (state.litLinks.has(l.id) ? (pinned?.id === l.id ? 2.6 : 2) : state.faded?.(l.id) ? 0.4
        : Math.min(1 + ((lineCount.get(l.id) ?? 1) - 1) * 0.45, 4.5)))
      .linkDirectionalParticles((l: L) => (state.litLinks.has(l.id) ? 3 : 0))
      .linkDirectionalParticleColor(() => ACCENT)
      .linkDirectionalArrowColor((l: L) => (state.litLinks.has(l.id) ? ACCENT : l.old && compare !== "before" ? OLD : LINK));
  }, [state, ready, hiddenLabels, compare, overview, pinned, lineCount]);

  // ------------------------------------------------------------------ controls
  const fit = () => { const g = fg.current; if (!g) return; g.zoomToFit(500, 12); setTimeout(() => { closer(g, 0.8); applyFog(g); }, 560); };
  const target = () => (fg.current?.controls() as { target?: { x: number; y: number; z: number } } | undefined)?.target ?? { x: 0, y: 0, z: 0 };
  const zoomBy = (f: number) => {
    const g = fg.current;
    if (!g) return;
    const c = g.cameraPosition(), t = target();
    g.cameraPosition({ x: t.x + (c.x - t.x) * f, y: t.y + (c.y - t.y) * f, z: t.z + (c.z - t.z) * f }, t, 300);
  };
  const resetView = () => {
    const g = fg.current;
    if (!g) return;
    const c = g.cameraPosition(), t = target();
    const d = Math.hypot(c.x - t.x, c.y - t.y, c.z - t.z);
    g.cameraPosition({ x: t.x, y: t.y, z: t.z + d }, t, 500); // straight on, as the 2D view
  };
  const find = () => {
    const g = fg.current;
    const q = query.trim().toLowerCase();
    if (!g || !q) return;
    const hit = [...cache.current.values()].find((n) => n.id.toLowerCase().includes(q) || n.name.toLowerCase().includes(q));
    if (!hit || hit.x === undefined) return;
    const d = 90, len = Math.hypot(hit.x, hit.y ?? 0, hit.z ?? 0) || 1, k = 1 + d / len;
    g.cameraPosition({ x: hit.x * k, y: (hit.y ?? 0) * k, z: (hit.z ?? 0) * k }, { x: hit.x, y: hit.y ?? 0, z: hit.z ?? 0 }, 800);
    onSelect(hit.id);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "Escape") setPinned(null);
      if (e.key === "f") fit();
      if (e.key === "d") setDim((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

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

  return (
    <div className="relative isolate h-full w-full overflow-hidden">
      <div ref={host} className="absolute inset-0 z-0" data-testid="graph-3d" />

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

      {labelCounts.length > 0 && (
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
              <span className="font-mono text-ink-3">{n}</span>
              {hiddenLabels.has(label) ? <EyeOff size={12} className="text-ink-3" /> : <Eye size={12} className="text-ink-3" />}
            </button>
          ))}
          {legendOpen && typeCounts.length > 0 && <p className="mb-1 mt-2 text-xs font-medium text-ink-2">Relationships</p>}
          {legendOpen && typeCounts.map(([type, n]) => (
            <button key={type} onClick={() => toggle(hiddenTypes, type, setHiddenTypes)} aria-pressed={!hiddenTypes.has(type)}
                    className={`flex w-full items-center gap-1.5 rounded px-1 py-0.5 hover:bg-raised ${hiddenTypes.has(type) ? "opacity-40" : ""}`}>
              <span className="h-px w-3 bg-ink-3" aria-hidden />
              <span className="flex-1 truncate text-left font-mono text-[11px] text-ink-2">{type}</span>
              <span className="font-mono text-ink-3">{n}</span>
            </button>
          ))}
        </div>
      )}

      <div className="absolute bottom-3 right-3 z-10 flex flex-col items-center gap-0.5 rounded border border-line bg-panel p-1">
        <IconButton label="Zoom in" onClick={() => zoomBy(0.75)}><ZoomIn size={16} /></IconButton>
        <IconButton label="Zoom out" onClick={() => zoomBy(1.33)}><ZoomOut size={16} /></IconButton>
        <IconButton label="Fit (f)" onClick={fit}><Maximize size={16} /></IconButton>
        <IconButton label="Face front" onClick={resetView}><RotateCcw size={16} /></IconButton>
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
        <IconButton label="Dim (d)" active={dim} onClick={() => setDim((v) => !v)}><SunDim size={16} /></IconButton>
      </div>
    </div>
  );
}
