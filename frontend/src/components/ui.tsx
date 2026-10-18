"use client";

import type { ReactNode } from "react";
import type { Track } from "@/lib/api";
import { labelOfId, shortId, styleOf, type Shape } from "@/lib/entities";

// Shared primitives. notes/design-direction.md: colour only for meaning, one container level, no icon set for types.

// ------------------------------------------------------------------ track names (text, no colour)
const TRACK_NAME: Record<Track, string> = { "01": "Act", "02": "Remember", "03": "Brain" };

export function TrackTags({ tracks }: { tracks: Track[] }) {
  const list = [...new Set(tracks)].sort();
  if (!list.length) return null;
  return (
    <span className="shrink-0 font-mono text-[11px] text-ink-3">
      {list.map((t) => `${t} ${TRACK_NAME[t]}`).join(" · ")}
    </span>
  );
}

// ------------------------------------------------------------------ status word (tint only, no border)
const TONE = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  info: "bg-accent-soft text-accent-ink",
  muted: "bg-raised text-ink-2",
} as const;
export type Tone = keyof typeof TONE;

const STATUS_TONE: Record<string, Tone> = {
  open: "warn", claimed: "info", done: "ok", proposed: "warn", approved: "info", executed: "ok", rejected: "muted", blocked: "bad",
};
export const toneOf = (status: string): Tone => STATUS_TONE[status] ?? "muted";

export function Chip({ tone = "muted", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-[2px] px-1.5 py-px text-xs font-medium ${TONE[tone]}`}>
      {children}
    </span>
  );
}

// ------------------------------------------------------------------ entity reference (shape of its type + id)
export function EntityChip({ id, name, struck, compact, onOpen, onHover }: {
  id: string; name?: string; struck?: boolean; compact?: boolean; // compact: shape only, a citation marker after a name
  onOpen?: (id: string) => void; onHover?: (id: string | null) => void;
}) {
  return (
    <button type="button" title={id} aria-label={compact ? id : undefined}
            onClick={(e) => { e.stopPropagation(); onOpen?.(id); }}
            onMouseEnter={() => onHover?.(id)} onMouseLeave={() => onHover?.(null)}
            className={`inline-flex max-w-full items-center gap-1 rounded-[2px] px-0.5 align-baseline font-mono text-[12px] text-ink-2 hover:bg-raised hover:text-ink ${struck ? "line-through opacity-70" : ""}`}>
      <ShapeSwatch label={labelOfId(id)} size={9} />
      {!compact && <span className="truncate underline decoration-line-strong decoration-dotted underline-offset-[3px]">{name ?? shortId(id)}</span>}
    </button>
  );
}

// ------------------------------------------------------------------ shape swatch (the canvas vocabulary)
const POLY: Partial<Record<Shape, string>> = {
  hexagon: "3,1 9,1 11,6 9,11 3,11 1,6",
  triangle: "6,1 11,11 1,11",
  diamond: "6,0.5 11.5,6 6,11.5 0.5,6",
  tag: "1,2 8,2 11,6 8,10 1,10",
  "round-tag": "1,2 8,2 11,6 8,10 1,10",
  octagon: "4,1 8,1 11,4 11,8 8,11 4,11 1,8 1,4",
};

export function ShapeSwatch({ label, size = 12 }: { label: string; size?: number }) {
  const { colour, shape } = styleOf(label);
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden className="shrink-0">
      {shape === "ellipse" ? <circle cx="6" cy="6" r="5" fill={colour} />
        : shape === "round-rectangle" ? <rect x="1" y="2" width="10" height="8" rx="2.5" fill={colour} />
        : shape === "rectangle" ? <rect x="1.5" y="1.5" width="9" height="9" fill={colour} />
        : <polygon points={POLY[shape]} fill={colour} />}
    </svg>
  );
}

// ------------------------------------------------------------------ icon-only control (always labelled)
export function IconButton({ label, onClick, active, children, disabled }: {
  label: string; onClick: () => void; active?: boolean; children: ReactNode; disabled?: boolean;
}) {
  return (
    <button type="button" title={label} aria-label={label} aria-pressed={active} onClick={onClick} disabled={disabled}
            className={`grid h-8 w-8 place-items-center rounded text-ink-2 hover:bg-raised disabled:opacity-40 ${active ? "bg-accent-soft text-accent-ink" : ""}`}>
      {children}
    </button>
  );
}
