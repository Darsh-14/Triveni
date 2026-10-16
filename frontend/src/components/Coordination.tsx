"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ActionInfo, type HandoffInfo } from "@/lib/api";

const STATUS: Record<string, string> = {
  open: "bg-amber-100 text-amber-800", claimed: "bg-blue-100 text-blue-800", done: "bg-green-100 text-green-800",
  proposed: "bg-amber-100 text-amber-800", blocked: "bg-red-100 text-red-800", executed: "bg-green-100 text-green-800",
  rejected: "bg-gray-200 text-gray-700", approved: "bg-blue-100 text-blue-800",
};

const Chip = ({ s }: { s: string }) => <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${STATUS[s] ?? ""}`}>{s}</span>;

/** Track 02 coordination + Track 01 approvals: everything shown here is read from Handoff and Action nodes. */
export default function Coordination({ tenant, refreshKey, onResult }: {
  tenant: string; refreshKey: number; onResult: (label: string, r: Awaited<ReturnType<typeof api.runRemediation>>) => void;
}) {
  const [handoffs, setHandoffs] = useState<HandoffInfo[]>([]);
  const [actions, setActions] = useState<ActionInfo[]>([]);
  const [approver, setApprover] = useState("per:meera-pillai");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [h, a] = await Promise.all([api.handoffs(tenant), api.actions(tenant)]);
    setHandoffs(h);
    setActions(a);
  }, [tenant]);

  useEffect(() => {
    let live = true;
    Promise.all([api.handoffs(tenant), api.actions(tenant)])
      .then(([h, a]) => { if (live) { setHandoffs(h); setActions(a); } })
      .catch((e) => live && setNote(e.message));
    return () => { live = false; };
  }, [tenant, refreshKey]);

  const runRemediation = async () => {
    setBusy(true); setNote(null);
    try {
      const r = await api.runRemediation(tenant);
      if (!r.handoff) setNote("No open handoff for agent:remediation.");
      else onResult(`Remediation agent on ${r.handoff.id} (${r.handoff.incident})`, r);
      await reload();
    } catch (e) { setNote((e as Error).message); } finally { setBusy(false); }
  };

  const decideAction = async (id: string, approve: boolean) => {
    setBusy(true); setNote(null);
    try {
      const r = await api.decide(tenant, id, approver, approve);
      setNote(approve ? `${id} executed → ${r.delivered_to} (outbox ${r.outbox})` : `${id} rejected`);
      await reload();
    } catch (e) { setNote((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center gap-2">
        <button disabled={busy} onClick={runRemediation}
                className="rounded bg-gray-900 px-2.5 py-1 font-medium text-white disabled:opacity-50">
          {busy ? "Working…" : "Run remediation agent"}
        </button>
        <label className="flex items-center gap-1 text-gray-600">
          approving as
          <input value={approver} onChange={(e) => setApprover(e.target.value)}
                 className="w-36 rounded border border-gray-300 px-1.5 py-0.5 font-mono" />
        </label>
      </div>
      {note && <p className="rounded bg-gray-100 p-1.5 text-gray-700">{note}</p>}

      <div>
        <p className="mb-1 font-semibold text-gray-700">Handoffs (graph nodes, the only channel between agents)</p>
        {handoffs.length === 0 && <p className="text-gray-400">None yet. Ask scenario #6 to have triage hand off.</p>}
        {handoffs.map((h) => (
          <div key={h.id} className="mb-1 rounded border border-gray-200 bg-white p-1.5">
            <div className="flex items-center gap-1.5">
              <Chip s={h.status} /><span className="font-mono">{h.id}</span>
              <span className="text-gray-500">{h.from} → {h.to} · {h.incident}</span>
            </div>
            <p className="mt-0.5 text-gray-700">{h.payload.summary}</p>
            {h.result && <p className="mt-0.5 text-gray-500">result: {h.result}</p>}
          </div>
        ))}
      </div>

      <div>
        <p className="mb-1 font-semibold text-gray-700">Actions (need a human; blocked when a current decision forbids them)</p>
        {actions.length === 0 && <p className="text-gray-400">No proposed actions.</p>}
        {actions.map((a) => (
          <div key={a.id} className="mb-1 rounded border border-gray-200 bg-white p-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip s={a.status} /><span className="font-mono">{a.kind}</span><span className="text-gray-500">→ {a.target}</span>
              <span className="text-gray-400">by {a.proposed_by}</span>
            </div>
            <p className="mt-0.5 text-gray-700">{String(a.args.title ?? a.args.reason ?? "")}</p>
            {a.blocked_by.length > 0 && <p className="mt-0.5 text-red-700">blocked by {a.blocked_by.join(", ")}</p>}
            {a.approved_by && <p className="mt-0.5 text-green-700">approved by {a.approved_by}{a.outbox ? ` · outbox ${a.outbox}` : ""}</p>}
            {a.status === "proposed" && (
              <div className="mt-1 flex gap-1.5">
                <button disabled={busy} onClick={() => decideAction(a.id, true)}
                        className="rounded bg-green-700 px-2 py-0.5 text-white disabled:opacity-50">Approve</button>
                <button disabled={busy} onClick={() => decideAction(a.id, false)}
                        className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-50">Reject</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
