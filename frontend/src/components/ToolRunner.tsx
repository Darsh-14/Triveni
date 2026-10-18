"use client";

import { useState } from "react";
import type { ToolInfo } from "@/lib/api";
import { TrackTags } from "./ui";

/** Form generated from a tool's JSON schema: run any read-only graph tool directly, no model involved. */
export default function ToolRunner({ tools, onRun, busy, initial }: {
  tools: ToolInfo[]; busy: boolean; onRun: (name: string, args: Record<string, unknown>) => void; initial?: string;
}) {
  const readTools = tools.filter((t) => t.read_only);
  const [name, setName] = useState(initial ?? readTools[0]?.name ?? "");
  const [args, setArgs] = useState<Record<string, unknown>>({});
  const tool = readTools.find((t) => t.name === name) ?? readTools[0];
  if (!tool) return null;

  const props = tool.input_schema.properties;
  const required = new Set(tool.input_schema.required ?? []);
  const set = (k: string, v: unknown) => setArgs((a) => ({ ...a, [k]: v }));
  const field = "mt-1 w-full rounded border border-line bg-panel px-2 py-1.5 text-sm text-ink";

  const submit = () => {
    const clean = Object.fromEntries(Object.entries(args).filter(([k, v]) => k in props && v !== "" && v !== undefined));
    onRun(tool.name, clean);
  };

  return (
    <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="space-y-3">
      <div className="flex items-center gap-2">
        <select value={tool.name} onChange={(e) => { setName(e.target.value); setArgs({}); }} aria-label="Tool"
                className="flex-1 rounded border border-line bg-panel px-2 py-1.5 font-mono text-sm text-ink">
          {readTools.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
        </select>
        <TrackTags tracks={tool.tracks} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        {Object.entries(props).map(([key, p]) => (
          <label key={key} className="font-mono text-xs text-ink-3">
            {key}{required.has(key) ? " *" : ""}
            {p.enum ? (
              <select value={String(args[key] ?? p.default ?? "")} className={field}
                      onChange={(e) => set(key, p.type === "integer" ? Number(e.target.value) : e.target.value)}>
                {!required.has(key) && <option value="">Any</option>}
                {p.enum.map((v) => <option key={String(v)} value={String(v)}>{String(v)}</option>)}
              </select>
            ) : p.type === "boolean" ? (
              <input type="checkbox" checked={Boolean(args[key])} onChange={(e) => set(key, e.target.checked)} className="ml-2" />
            ) : p.type === "array" ? (
              <input type="text" value={Array.isArray(args[key]) ? (args[key] as string[]).join(", ") : ""} className={field}
                     onChange={(e) => set(key, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
            ) : (
              <input type={p.type === "integer" ? "number" : "text"} value={String(args[key] ?? "")} className={field}
                     placeholder={p.default !== undefined ? String(p.default) : ""}
                     onChange={(e) => set(key, p.type === "integer" ? Number(e.target.value) : e.target.value)} />
            )}
          </label>
        ))}
      </div>
      <button disabled={busy} className="w-full rounded bg-ink py-1.5 text-sm font-medium text-white hover:bg-ink-2 disabled:opacity-50">
        Run
      </button>
    </form>
  );
}
