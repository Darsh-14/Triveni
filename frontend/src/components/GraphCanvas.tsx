"use client";

import { useEffect, useRef } from "react";
import type { Core, ElementDefinition } from "cytoscape";
import type { GraphEdge, GraphNode } from "@/lib/api";

// One colour per node label; same palette as the README diagram.
export const LABEL_COLOURS: Record<string, string> = {
  Service: "#2563eb",
  Team: "#7c3aed",
  Person: "#059669",
  Incident: "#dc2626",
  Decision: "#d97706",
  Document: "#6b7280",
  Deployment: "#0d9488",
  Episode: "#1d4ed8",
  Lesson: "#4338ca",
  Procedure: "#0369a1",
  Handoff: "#be185d",
  Action: "#b91c1c",
  Agent: "#334155",
};

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  highlight: Set<string>; // node ids and edge keys to emphasise
  onSelect?: (id: string) => void;
}

export const edgeKey = (e: GraphEdge) => `${e.type}:${e.source}->${e.target}`;

export default function GraphCanvas({ nodes, edges, highlight, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const cytoscape = (await import("cytoscape")).default; // browser-only library
      if (cancelled || !container.current) return;
      const ids = new Set(nodes.map((n) => n.id));
      const elements: ElementDefinition[] = [
        ...nodes.map((n) => ({
          data: { id: n.id, label: n.name.length > 28 ? n.name.slice(0, 26) + "…" : n.name, kind: n.label,
                  colour: LABEL_COLOURS[n.label] ?? "#94a3b8", hot: highlight.has(n.id) ? 1 : 0 },
        })),
        ...edges
          .filter((e) => ids.has(e.source) && ids.has(e.target))
          .map((e) => ({
            data: { id: edgeKey(e), source: e.source, target: e.target, label: e.type,
                    hot: highlight.has(edgeKey(e)) ? 1 : 0, old: e.superseded || e.stale ? 1 : 0 },
          })),
      ];
      cy.current?.destroy();
      cy.current = cytoscape({
        container: container.current,
        elements,
        minZoom: 0.2,
        maxZoom: 1.6, // small evidence graphs would otherwise be blown up to fill the canvas
        style: [
          { selector: "node", style: {
              "background-color": "data(colour)", label: "data(label)", "font-size": 8, color: "#1f2937", "min-zoomed-font-size": 6,
              "text-valign": "bottom", "text-margin-y": 3, width: 16, height: 16, opacity: 0.85 } },
          { selector: "node[hot = 1]", style: {
              width: 26, height: 26, "border-width": 3, "border-color": "#111827", opacity: 1, "font-size": 11,
              "font-weight": "bold" } },
          { selector: "edge", style: {
              width: 1, "line-color": "#cbd5e1", "target-arrow-color": "#cbd5e1", "target-arrow-shape": "triangle",
              "curve-style": "bezier", "arrow-scale": 0.7, opacity: 0.7 } },
          { selector: "edge[hot = 1]", style: {
              width: 3, "line-color": "#111827", "target-arrow-color": "#111827", label: "data(label)",
              "font-size": 8, "text-background-color": "#ffffff", "text-background-opacity": 1, opacity: 1 } },
          { selector: "edge[old = 1]", style: {
              "line-style": "dashed", "line-color": "#ef4444", "target-arrow-color": "#ef4444" } },
        ],
        layout: { name: "cose", animate: false, padding: 40,
                  nodeRepulsion: () => (nodes.length > 30 ? 60000 : 12000),
                  idealEdgeLength: () => (nodes.length > 30 ? 110 : 80) },
      });
      cy.current.on("tap", "node", (evt) => onSelect?.(evt.target.id()));
    })();
    return () => {
      cancelled = true;
    };
  }, [nodes, edges, highlight, onSelect]);

  useEffect(() => () => cy.current?.destroy(), []);

  return <div ref={container} className="h-full w-full" data-testid="graph-canvas" />;
}
