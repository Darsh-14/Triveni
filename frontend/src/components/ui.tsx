"use client";

import { createElement, type ReactNode } from "react";
import {
  BookOpen, Bot, Box, FileText, Gavel, History, Lightbulb, ListChecks, MessageSquare, MessagesSquare, Rocket,
  Server, Siren, Ticket, User, Users, Zap, ArrowRightLeft, FileWarning, Database,
} from "lucide-react";
import type React from "react";
import type { Track } from "@/lib/api";
import { labelOfId, shortId, styleOf, type Shape } from "@/lib/entities";

const LABEL_ICON: Record<string, typeof Server> = {
  Service: Server, Person: User, Team: Users, Deployment: Rocket, Incident: Siren, Decision: Gavel, Document: FileText,
  Episode: History, Lesson: Lightbulb, Procedure: ListChecks, Agent: Bot, Handoff: ArrowRightLeft, Action: Zap,
  Conversation: MessagesSquare, Message: MessageSquare,
};

export const iconForLabel = (label: string) => LABEL_ICON[label] ?? Box;

const DOC_ICON: Record<string, typeof Server> = {
  runbook: BookOpen, postmortem: FileWarning, adr: Gavel, ticket: Ticket, chat: MessageSquare, registry: Database,
};
export const iconForDocKind = (kind: string) => DOC_ICON[kind] ?? FileText;

type IconProps = { size?: number; className?: string; style?: React.CSSProperties };
/** Icon for a node label or a document kind (createElement: the icon is picked from a static map). */
export const LabelIcon = ({ label, ...p }: { label: string } & IconProps) => createElement(iconForLabel(label), { "aria-hidden": true, ...p });
export const DocIcon = ({ kind, ...p }: { kind: string } & IconProps) => createElement(iconForDocKind(kind), { "aria-hidden": true, ...p });

// ------------------------------------------------------------------ track tags (neutral outline + number)
const TRACK_NAME: Record<Track, string> = { "01": "Act", "02": "Remember", "03": "Brain" };
const TRACK_RULE: Record<Track, string> = { "01": "bg-t01", "02": "bg-t02", "03": "bg-t03" };

export function TrackTags({ tracks }: { tracks: Track[] }) {
  return (
    <span className="inline-flex shrink-0 gap-1">
      {[...new Set(tracks)].sort().map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded border border-line-strong bg-panel px-1.5 py-0.5 text-[11px] font-medium text-ink-2">
          <span className={`h-2 w-2 rounded-full ${TRACK_RULE[t]}`} aria-hidden />
          {t} {TRACK_NAME[t]}
        </span>
      ))}
    </span>
  );
}

// ------------------------------------------------------------------ status chip (icon-less word, semantic colour)
const TONE = {
  ok: "bg-ok-soft text-ok border-ok/30",
  warn: "bg-warn-soft text-warn border-warn/30",
  bad: "bg-bad-soft text-bad border-bad/30",
  info: "bg-accent-soft text-accent border-accent/30",
  muted: "bg-raised text-ink-3 border-line",
} as const;
export type Tone = keyof typeof TONE;

const STATUS_TONE: Record<string, Tone> = {
  open: "warn", claimed: "info", done: "ok", proposed: "warn", approved: "info", executed: "ok", rejected: "muted", blocked: "bad",
};
export const toneOf = (status: string): Tone => STATUS_TONE[status] ?? "muted";

export function Chip({ tone = "muted", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium ${TONE[tone]}`}>
      {children}
    </span>
  );
}

// ------------------------------------------------------------------ entity chip (type icon + id, clickable)
export function EntityChip({ id, name, struck, compact, onOpen, onHover }: {
  id: string; name?: string; struck?: boolean; compact?: boolean; // compact: icon only, a citation marker after a name
  onOpen?: (id: string) => void; onHover?: (id: string | null) => void;
}) {
  const label = labelOfId(id);
  return (
    <button type="button" title={id} aria-label={compact ? id : undefined}
            onClick={(e) => { e.stopPropagation(); onOpen?.(id); }}
            onMouseEnter={() => onHover?.(id)} onMouseLeave={() => onHover?.(null)}
            className={`inline-flex max-w-full items-center gap-1 rounded border border-line bg-panel px-1.5 py-px align-baseline font-mono text-[12px] text-ink-2 hover:border-line-strong hover:bg-raised ${struck ? "line-through opacity-70" : ""}`}>
      <LabelIcon label={label} size={12} style={{ color: styleOf(label).colour }} className="shrink-0" />
      {!compact && <span className="truncate">{name ?? shortId(id)}</span>}
    </button>
  );
}

// ------------------------------------------------------------------ shape swatch (legend)
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

// ------------------------------------------------------------------ small icon button with tooltip
export function IconButton({ label, onClick, active, children, disabled }: {
  label: string; onClick: () => void; active?: boolean; children: ReactNode; disabled?: boolean;
}) {
  return (
    <button type="button" title={label} aria-label={label} aria-pressed={active} onClick={onClick} disabled={disabled}
            className={`grid h-8 w-8 place-items-center rounded-md text-ink-2 hover:bg-raised disabled:opacity-40 ${active ? "bg-accent-soft text-accent" : ""}`}>
      {children}
    </button>
  );
}
