"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Search } from "./icons";

/* Command palette (Linear / Vercel / Raycast): one searchable list of everything you can do or open.
   Combobox pattern: focus stays in the input, a virtual highlight moves through the options. */

export interface PaletteItem {
  id: string;        // stable key
  group: string;     // section title
  label: string;
  hint?: string;     // right-aligned (id, shortcut)
  icon?: ReactNode;
  keywords?: string; // extra text to match
  run: () => void;
}

const GROUP_ORDER = ["Scenarios", "Actions", "Nodes", "Conversations", "Tools"];
const LIMIT_PER_GROUP = 8;

/** Rank an item: a substring of the label beats a substring of its hint or keywords, which beats a fuzzy match.
    Fuzzy (every query character in order) is tried on the label only: long keyword text matches almost anything. */
function rank(it: PaletteItem, q: string): number {
  if (!q) return 1;
  const label = it.label.toLowerCase();
  const at = label.indexOf(q);
  if (at >= 0) return 3000 - at + (at === 0 || /[\s:_-]/.test(label[at - 1]) ? 200 : 0);
  if (`${it.hint ?? ""} ${it.keywords ?? ""}`.toLowerCase().includes(q)) return 2000;
  return fuzzy(label, q);
}

/** Fuzzy score: every query character in order; contiguous and close matches score higher. */
function fuzzy(t: string, q: string): number {
  let at = 0, total = 0, run = 0, first = -1;
  for (const ch of q) {
    const i = t.indexOf(ch, at);
    if (i < 0) return 0;
    if (first < 0) first = i;
    run = i === at ? run + 1 : 0;
    total += 10 + run * 5 - Math.min(i - at, 10);
    at = i + 1;
  }
  return at - first <= q.length * 2 + 2 ? total : 0; // letters scattered over a long label are not a match
}

export default function CommandPalette({ open, onClose, items }: { open: boolean; onClose: () => void; items: PaletteItem[] }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery(""); setActive(0); // eslint-disable-line react-hooks/set-state-in-effect
    requestAnimationFrame(() => input.current?.focus());
  }, [open]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const scored = items
      .filter((it) => q || it.group !== "Nodes") // nodes only when searching: there are hundreds
      .map((it) => ({ it, s: rank(it, q) }))
      .filter((x) => x.s > 0);
    const groups = new Map<string, typeof scored>();
    scored.sort((a, b) => b.s - a.s).forEach((x) => groups.set(x.it.group, [...(groups.get(x.it.group) ?? []), x]));
    const fixed = (g: string) => GROUP_ORDER.indexOf(g) + 1 || 99;
    return [...groups.entries()] // typing: the group with the best match first; empty query: fixed order
      .sort(([a, xa], [b, xb]) => (q ? xb[0].s - xa[0].s : 0) || fixed(a) - fixed(b))
      .map(([group, xs]) => ({ group, items: xs.slice(0, LIMIT_PER_GROUP).map((x) => x.it) }));
  }, [items, query]);
  const flat = results.flatMap((g) => g.items);
  const indexOf = new Map(flat.map((it, i) => [it.id, i]));

  useEffect(() => {
    list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const choose = (it: PaletteItem | undefined) => { if (!it) return; onClose(); it.run(); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, flat.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); choose(flat[active]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-ink/30 pt-[12vh]" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={(e) => e.stopPropagation()}
           className="w-[560px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-md border border-line bg-panel">
        <div className="flex items-center gap-2 border-b border-line px-3">
          <Search size={16} className="text-ink-3" aria-hidden />
          <input ref={input} value={query} onChange={(e) => { setQuery(e.target.value); setActive(0); }} onKeyDown={onKey}
                 role="combobox" aria-expanded="true" aria-controls="palette-list" aria-autocomplete="list"
                 aria-activedescendant={flat[active] ? `palette-${active}` : undefined} placeholder="Search" aria-label="Search"
                 className="h-12 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3 focus-visible:outline-none" />
          <kbd className="rounded border border-line bg-raised px-1.5 font-mono text-[11px] text-ink-3">Esc</kbd>
        </div>
        <div ref={list} id="palette-list" role="listbox" className="max-h-[55vh] overflow-auto p-1.5">
          {flat.length === 0 && <p className="px-3 py-6 text-center text-sm text-ink-3">No results</p>}
          {results.map((g) => (
            <div key={g.group} role="group" aria-label={g.group} className="mb-1">
              <p className="px-2 pb-1 pt-2 text-xs font-medium text-ink-2">{g.group}</p>
              {g.items.map((it) => {
                const i = indexOf.get(it.id)!;
                return (
                  <div key={it.id} id={`palette-${i}`} data-index={i} role="option" aria-selected={i === active}
                       onMouseMove={() => setActive(i)} onClick={() => choose(it)}
                       className={`flex cursor-pointer items-center gap-2.5 rounded px-2 py-1.5 text-[13px] ${i === active ? "bg-accent-soft text-ink" : "text-ink-2"}`}>
                    <span className="grid w-4 shrink-0 place-items-center text-ink-3">{it.icon}</span>
                    <span className="min-w-0 flex-1 truncate">{it.label}</span>
                    {it.hint && <span className="shrink-0 font-mono text-[11px] text-ink-3">{it.hint}</span>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
