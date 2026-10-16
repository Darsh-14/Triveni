"use client";

import { useState } from "react";
import type { ToolInfo } from "@/lib/api";

/** Form generated from a tool's JSON schema: run any graph tool directly, no model involved. */
export default function ToolRunner({ tools, onRun, busy }: {
  tools: ToolInfo[]; busy: boolean; onRun: (name: string, args: Record<string, unknown>) => void;
}) {
  const readTools = tools.filter((t) => t.read_only);
  const [name, setName] = useState(readTools[0]?.name ?? "");
  const [args, setArgs] = useState<Record<string, unknown>>({});
  const tool = readTools.find((t) => t.name === name) ?? readTools[0];
  if (!tool) return null;

  const props = tool.input_schema.properties;
  const required = new Set(tool.input_schema.required ?? []);
  const set = (k: string, v: unknown) => setArgs((a) => ({ ...a, [k]: v }));

  const submit = () => {
    const clean = Object.fromEntries(Object.entries(args).filter(([k, v]) => k in props && v !== "" && v !== undefined));
    onRun(tool.name, clean);
  };

  return (
    <div className="space-y-2">
      <select value={tool.name} onChange={(e) => { setName(e.target.value); setArgs({}); }}
              className="w-full rounded border border-gray-300 bg-white px-2 py-1 text-sm">
        {readTools.map((t) => <option key={t.name} value={t.name}>{t.name} (Track {t.tracks.join("/")})</option>)}
      </select>
      <p className="text-[11px] text-gray-500">{tool.description}</p>
      <div className="grid grid-cols-2 gap-2">
        {Object.entries(props).map(([key, p]) => (
          <label key={key} className="text-xs text-gray-700">
            {key}{required.has(key) ? " *" : ""}
            {p.enum ? (
              <select value={String(args[key] ?? p.default ?? "")} onChange={(e) =>
                        set(key, p.type === "integer" ? Number(e.target.value) : e.target.value)}
                      className="mt-0.5 w-full rounded border border-gray-300 bg-white px-1.5 py-1 text-sm">
                {!required.has(key) && <option value="">—</option>}
                {p.enum.map((v) => <option key={String(v)} value={String(v)}>{String(v)}</option>)}
              </select>
            ) : p.type === "boolean" ? (
              <input type="checkbox" checked={Boolean(args[key])} onChange={(e) => set(key, e.target.checked)}
                     className="ml-2" />
            ) : (
              <input type={p.type === "integer" ? "number" : "text"} placeholder={p.description ?? ""}
                     value={String(args[key] ?? "")}
                     onChange={(e) => set(key, p.type === "integer" ? Number(e.target.value) : e.target.value)}
                     className="mt-0.5 w-full rounded border border-gray-300 px-1.5 py-1 text-sm" />
            )}
          </label>
        ))}
      </div>
      <button disabled={busy} onClick={submit}
              className="w-full rounded bg-gray-900 py-1.5 text-sm font-medium text-white disabled:opacity-50">
        Run {tool.name}
      </button>
    </div>
  );
}
