"use client";

import { useRef } from "react";

/* Drag handle between two panes (split-pane frame, as in Claude Artifacts / ChatGPT Canvas / Retool).
   ARIA separator: focusable, arrow keys move it, double-click resets the width. */
export default function Splitter({ value, min, max, reset, grow, onChange, label }: {
  value: number; min: number; max: number; reset: number;
  grow: "right" | "left"; // dragging right makes the pane wider ("right": pane on the left) or narrower ("left")
  onChange: (w: number) => void; label: string;
}) {
  const start = useRef<{ x: number; w: number } | null>(null);
  const clamp = (w: number) => Math.round(Math.min(max, Math.max(min, w)));
  const sign = grow === "right" ? 1 : -1;

  return (
    <div role="separator" aria-orientation="vertical" aria-label={label} aria-valuenow={value} aria-valuemin={min}
         aria-valuemax={max} tabIndex={0} title={label}
         onPointerDown={(e) => { start.current = { x: e.clientX, w: value }; e.currentTarget.setPointerCapture(e.pointerId); }}
         onPointerMove={(e) => { if (start.current) onChange(clamp(start.current.w + sign * (e.clientX - start.current.x))); }}
         onPointerUp={() => { start.current = null; }}
         onDoubleClick={() => onChange(reset)}
         onKeyDown={(e) => {
           if (e.key === "ArrowLeft") { e.preventDefault(); onChange(clamp(value - sign * 16)); }
           if (e.key === "ArrowRight") { e.preventDefault(); onChange(clamp(value + sign * 16)); }
         }}
         className="group relative z-10 -mx-1 w-2 shrink-0 cursor-col-resize touch-none select-none outline-none">
      <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line transition-colors group-hover:w-0.5 group-hover:bg-accent group-focus-visible:w-0.5 group-focus-visible:bg-accent" />
    </div>
  );
}
