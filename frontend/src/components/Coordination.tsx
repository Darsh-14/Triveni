"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Bot, Check, LoaderCircle } from "lucide-react";
import { api, type ActionInfo, type AgentResult, type HandoffInfo, type Person } from "@/lib/api";
import { Chip, EntityChip, toneOf } from "./ui";

/* Approvals (Track 01) and handoffs (Track 02). Everything here is read from Action and Handoff nodes. */

const HANDOFF_STEPS = ["open", "claimed", "done"];

function Stepper({ status }: { status: string }) {
  const at = HANDOFF_STEPS.indexOf(status);
  return (
    <ol className="flex items-center gap-1 text-[11px]">
      {HANDOFF_STEPS.map((s, i) => (
        <li key={s} className="flex items-center gap-1">
          <span className={`grid h-4 w-4 place-items-center rounded-full border ${i <= at ? "border-accent bg-accent text-white" : "border-line-strong text-ink-3"}`}>
            {i < at || (i === at && s === "done") ? <Check size={10} /> : null}
          </span>
          <span className={i === at ? "font-semibold text-ink" : "text-ink-3"}>{s}</span>
          {i < HANDOFF_STEPS.length - 1 && <span className={`h-px w-4 ${i < at ? "bg-accent" : "bg-line-strong"}`} aria-hidden />}
        </li>
      ))}
    </ol>
  );
}

export default function Approvals({ tenant, refreshKey, onOpen, onResult, onChanged }: {
  tenant: string; refreshKey: number; onOpen: (id: string) => void;
  onResult: (label: string, r: AgentResult) => void; onChanged: () => void;
}) {
  const [handoffs, setHandoffs] = useState<HandoffInfo[]>([]);
  const [actions, setActions] = useState<ActionInfo[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [approver, setApprover] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [h, a] = await Promise.all([api.handoffs(tenant), api.actions(tenant)]);
    setHandoffs(h);
    setActions(a);
  }, [tenant]);

  useEffect(() => {
    let live = true;
    Promise.all([api.handoffs(tenant), api.actions(tenant), api.people(tenant)])
      .then(([h, a, p]) => {
        if (!live) return;
        setHandoffs(h); setActions(a); setPeople(p);
        setApprover((cur) => (p.some((x) => x.id === cur) ? cur : (p.find((x) => /manager|lead|director/i.test(x.role ?? ""))?.id ?? p[0]?.id ?? "")));
      })
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [tenant, refreshKey]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await fn(); await reload(); onChanged(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const runRemediation = () => run(async () => {
    const r = await api.runRemediation(tenant);
    if (!r.handoff) { setError("No open handoff"); return; }
    if (r.result) onResult(`Remediation · ${r.handoff.id} · ${r.handoff.incident}`, r.result);
  });

  const decide = (id: string, approve: boolean) => run(async () => { await api.decide(tenant, id, approver, approve); });

  const order = ["proposed", "blocked", "approved", "executed", "rejected"];
  const sorted = [...actions].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status) || b.ts.localeCompare(a.ts));

  return (
    <div className="space-y-5 text-xs">
      {error && <p className="rounded bg-bad-soft px-2 py-1.5 text-bad">{error}</p>}

      <section>
        <div className="mb-2 flex items-center gap-2">
          <h3 className="text-[13px] font-semibold text-ink">Actions <span className="font-mono font-normal text-ink-3">{actions.length}</span></h3>
          <label className="ml-auto flex items-center gap-1 text-ink-3">
            Approver
            <select value={approver} onChange={(e) => setApprover(e.target.value)}
                    className="max-w-40 rounded border border-line bg-panel px-1.5 py-1 text-xs text-ink">
              {people.map((p) => <option key={p.id} value={p.id}>{p.name}{p.role ? ` · ${p.role}` : ""}</option>)}
            </select>
          </label>
        </div>
        {sorted.length === 0 && <p className="text-ink-3">No actions</p>}
        <div className="divide-y divide-line border-y border-line">
          {sorted.map((a) => (
            <div key={a.id} className={`py-2.5 ${a.status === "proposed" ? "bg-warn-soft/50 px-2 -mx-2" : ""}`}>
              <div className="flex flex-wrap items-center gap-1.5">
                <Chip tone={toneOf(a.status)}>{a.status}</Chip>
                <span className="font-mono font-semibold text-ink">{a.kind}</span>
                <EntityChip id={a.target} onOpen={onOpen} />
                <span className="ml-auto font-mono text-[11px] text-ink-3">{a.id}</span>
              </div>
              {(a.args.title || a.args.reason) ? <p className="mt-1.5 text-[13px] text-ink-2">{String(a.args.title ?? a.args.reason)}</p> : null}
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-ink-3">
                <EntityChip id={a.proposed_by} onOpen={onOpen} />
                {a.blocked_by.map((d) => <EntityChip key={d} id={d} onOpen={onOpen} />)}
                {a.approved_by && <EntityChip id={a.approved_by} onOpen={onOpen} />}
                {a.outbox && <Chip tone="ok">{a.outbox}</Chip>}
              </div>
              {a.status === "proposed" && (
                <div className="mt-2 flex gap-1.5">
                  <button disabled={busy || !approver} onClick={() => decide(a.id, true)}
                          className="rounded bg-ink px-3 py-1 font-medium text-on-ink hover:bg-ink-2 disabled:opacity-50">Approve</button>
                  <button disabled={busy || !approver} onClick={() => decide(a.id, false)}
                          className="rounded border border-line-strong px-3 py-1 font-medium text-ink-2 hover:bg-raised disabled:opacity-50">Reject</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="mb-2 flex items-center gap-2">
          <h3 className="text-[13px] font-semibold text-ink">Handoffs <span className="font-mono font-normal text-ink-3">{handoffs.length}</span></h3>
          <button disabled={busy} onClick={runRemediation}
                  className="ml-auto inline-flex items-center gap-1 rounded border border-line-strong px-2 py-1 font-medium text-ink-2 hover:bg-raised disabled:opacity-50">
            {busy ? <LoaderCircle size={14} className="animate-spin" aria-hidden /> : <Bot size={14} aria-hidden />}{busy ? "Running" : "Run remediation"}
          </button>
        </div>
        {handoffs.length === 0 && <p className="text-ink-3">No handoffs</p>}
        <div className="divide-y divide-line border-y border-line">
          {handoffs.map((h) => (
            <div key={h.id} className="py-2.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <EntityChip id={h.from} onOpen={onOpen} /><ArrowRight size={12} className="text-ink-3" aria-label="to" /><EntityChip id={h.to} onOpen={onOpen} />
                {h.incident && <EntityChip id={h.incident} onOpen={onOpen} />}
                <span className="ml-auto font-mono text-[11px] text-ink-3">{h.id}</span>
              </div>
              <div className="mt-2"><Stepper status={h.status} /></div>
              {h.payload.summary && <p className="mt-1.5 text-[13px] text-ink-2">{h.payload.summary}</p>}
              {h.result && <p className="mt-1 text-[13px] text-ink-3">{h.result}</p>}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
