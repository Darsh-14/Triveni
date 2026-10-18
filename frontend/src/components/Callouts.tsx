"use client";

import type { ReactNode } from "react";
import type { Step, Track } from "@/lib/api";
import { Chip, EntityChip, toneOf } from "./ui";

/* Data callouts on an answer card: fields from a step's result data, no sentences.
   One renderer per tool; a tool without a renderer shows nothing here (its data stays under Details). */

type Rec = Record<string, unknown>;
const arr = (v: unknown): Rec[] => (Array.isArray(v) ? (v as Rec[]) : []);
const str = (v: unknown) => (v == null ? "" : String(v));
const svcId = (s: string) => (s.includes(":") ? s : `svc:${s}`);

interface Ctx { onOpen: (id: string) => void; onHover: (id: string | null) => void; onApprovals: () => void }

// one container level: a callout is a heading and rows under a rule, not a boxed card with a coloured stripe
function Box({ title, children }: { title: string; track?: Track; children: ReactNode }) {
  return (
    <section className="border-t border-line pt-2.5">
      <h4 className="mb-1.5 text-[13px] font-semibold text-ink">{title}</h4>
      <div className="space-y-1.5 text-[13px] text-ink-2">{children}</div>
    </section>
  );
}

function Row({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-20 shrink-0 text-xs text-ink-3">{k}</span>
      {children}
    </div>
  );
}

const chips = (items: Rec[], c: Ctx, idKey = "id", nameKey = "name") =>
  items.map((x) => <EntityChip key={str(x[idKey])} id={str(x[idKey])} name={x[nameKey] ? str(x[nameKey]) : undefined} onOpen={c.onOpen} onHover={c.onHover} />);

const RENDER: Record<string, (d: Rec, c: Ctx) => ReactNode> = {
  blast_radius: (d, c) => {
    const svc = (d.service ?? {}) as Rec;
    const affected = arr(d.affected);
    const byHop = new Map<number, Rec[]>();
    affected.forEach((a) => byHop.set(Number(a.hops), [...(byHop.get(Number(a.hops)) ?? []), a]));
    return (
      <Box title="Page" track="01">
        <Row k="On call">{svc.on_call ? <EntityChip id={str(svc.on_call)} name={str(svc.on_call_name)} onOpen={c.onOpen} onHover={c.onHover} /> : <Chip tone="bad">none</Chip>}</Row>
        <Row k="Owner">{svc.team ? <EntityChip id={str(svc.team)} name={str(svc.team_name)} onOpen={c.onOpen} onHover={c.onHover} /> : <Chip tone="bad">none</Chip>}</Row>
        {[...byHop.entries()].sort(([a], [b]) => a - b).map(([hops, list]) => (
          <Row key={hops} k={`${hops} hop${hops > 1 ? "s" : ""} · ${list.length}`}>{chips(list, c)}</Row>
        ))}
      </Box>
    );
  },

  owner_of: (d, c) => (
    <Box title="Page" track="03">
      <Row k="On call">{arr(d.on_call).length ? chips(arr(d.on_call), c) : <Chip tone="bad">none</Chip>}</Row>
      <Row k="Owner">{arr(d.owners).length ? chips(arr(d.owners), c) : <Chip tone="bad">none</Chip>}</Row>
    </Box>
  ),

  why_not: (d, c) => (d.exists ? null : (
    <Box title="No path" track="03">
      <pre className="overflow-x-auto rounded bg-raised px-2 py-1 font-mono text-[11px] text-ink-2">{str(d.checked)}</pre>
      <Row k="Rows"><Chip tone="bad">0</Chip></Row>
      {d.owner_team ? <Row k="Owner"><EntityChip id={str(d.owner_team)} onOpen={c.onOpen} onHover={c.onHover} /></Row> : null}
      {arr(d.suggested_contacts).length > 0 && <Row k="Knows it">{chips(arr(d.suggested_contacts), c)}</Row>}
    </Box>
  )),

  decision_trail: (d, c) => {
    const decisions = arr(d.decisions);
    const current = new Set((d.current as string[]) ?? []);
    return (
      <Box title="Decisions" track="03">
        {decisions.filter((x) => current.has(str(x.id))).map((x) => (
          <Row key={str(x.id)} k="Current">
            <EntityChip id={str(x.id)} onOpen={c.onOpen} onHover={c.onHover} />
            {((x.forbids as string[]) ?? []).map((f) => <Chip key={f} tone="bad">forbids {f}</Chip>)}
          </Row>
        ))}
        {decisions.filter((x) => !current.has(str(x.id))).length > 0 && (
          <Row k="Superseded">
            {decisions.filter((x) => !current.has(str(x.id))).map((x) => (
              <EntityChip key={str(x.id)} id={str(x.id)} struck onOpen={c.onOpen} onHover={c.onHover} />
            ))}
          </Row>
        )}
        {arr(d.stale_runbooks).length > 0 && (
          <Row k="Stale">
            {arr(d.stale_runbooks).map((r) => <EntityChip key={str(r.document)} id={str(r.document)} onOpen={c.onOpen} onHover={c.onHover} />)}
            <Chip tone="warn">cites {str(arr(d.stale_runbooks)[0].cites)}</Chip>
          </Row>
        )}
      </Box>
    );
  },

  recall: (d, c) => {
    const ep = arr(d.episodes)[0];
    if (!ep) return <Box title="Recalled" track="02"><Chip>none</Chip></Box>;
    return (
      <Box title="Recalled" track="02">
        <Row k="Episode">
          <EntityChip id={str(ep.id)} onOpen={c.onOpen} onHover={c.onHover} />
          <span className="text-xs text-ink-3">{str(ep.ts).slice(0, 10)}</span>
          {ep.outcome ? <Chip tone={str(ep.outcome) === "resolved" ? "ok" : "muted"}>{str(ep.outcome)}</Chip> : null}
        </Row>
        {arr(ep.procedures).map((p) => (
          <Row key={str(p.id)} k="Procedure">
            <EntityChip id={str(p.id)} name={str(p.name)} onOpen={c.onOpen} onHover={c.onHover} />
            <Chip tone="ok">{str(p.success_count)} ✓</Chip>
            <Chip tone={Number(p.fail_count) ? "bad" : "muted"}>{str(p.fail_count)} ✗</Chip>
          </Row>
        ))}
        {arr(ep.lessons).slice(0, 2).map((l) => (
          <Row key={str(l.id)} k="Lesson">
            <EntityChip id={str(l.id)} onOpen={c.onOpen} onHover={c.onHover} />
            <Chip tone={l.faded ? "muted" : "info"}>{str(l.effective_confidence)}</Chip>
          </Row>
        ))}
        {arr(d.episodes).length > 1 && <Row k="Also">{arr(d.episodes).slice(1).map((e) => <EntityChip key={str(e.id)} id={str(e.id)} onOpen={c.onOpen} onHover={c.onHover} />)}</Row>}
      </Box>
    );
  },

  similar_incidents: (d, c) => (
    <Box title="Prior incidents" track="03">
      {arr(d.incidents).slice(0, 3).map((i) => (
        <Row key={str(i.id)} k={str(i.ts_open).slice(0, 10)}>
          <EntityChip id={str(i.id)} name={str(i.title)} onOpen={c.onOpen} onHover={c.onHover} />
          {((i.resolved_by as string[]) ?? []).map((p) => <EntityChip key={p} id={p} onOpen={c.onOpen} onHover={c.onHover} />)}
          {((i.postmortems as string[]) ?? []).map((p) => <EntityChip key={p} id={p} onOpen={c.onOpen} onHover={c.onHover} />)}
        </Row>
      ))}
    </Box>
  ),

  key_people: (d, c) => (
    <Box title="Key people" track="01">
      {arr(d.people).slice(0, 5).map((p, i) => (
        <Row key={str(p.id)} k={`#${i + 1}`}>
          <EntityChip id={str(p.id)} name={str(p.name)} onOpen={c.onOpen} onHover={c.onHover} />
          <Chip tone="info">{arr(p.knows).length} services</Chip>
          {((p.teams_spanned as string[]) ?? []).map((t) => <Chip key={t}>{t}</Chip>)}
        </Row>
      ))}
    </Box>
  ),

  what_if: (d, c) => (
    <Box title="Without" track="03">
      <Row k="Person"><EntityChip id={str(d.entity)} name={str(d.name)} onOpen={c.onOpen} onHover={c.onHover} /></Row>
      <Row k="Lost">{arr(d.knowledge_lost).length || (d.knowledge_lost as string[] | undefined)?.length
        ? ((d.knowledge_lost as unknown[]) ?? []).map((x) => { const id = typeof x === "string" ? x : str((x as Rec).id ?? (x as Rec).service); return <EntityChip key={id} id={id} onOpen={c.onOpen} onHover={c.onHover} />; })
        : <Chip tone="ok">0</Chip>}</Row>
      <Row k="New orphans">{((d.new_orphans as unknown[]) ?? []).length
        ? ((d.new_orphans as unknown[]) ?? []).map((x) => { const id = typeof x === "string" ? x : str((x as Rec).id); return <EntityChip key={id} id={id} onOpen={c.onOpen} onHover={c.onHover} />; })
        : <Chip tone="ok">0</Chip>}</Row>
      {arr(d.new_key_people).length > 0 && <Row k="New key">{chips(arr(d.new_key_people), c)}</Row>}
    </Box>
  ),

  ingest_document: (d, c) => {
    const facts = arr(d.facts).filter((f) => f.action !== "unchanged");
    const impact = (d.impact ?? {}) as Rec;
    return (
      <Box title="Changed" track="03">
        {facts.map((f) => {
          const fact = str(f.fact);
          const rel = fact.slice(0, fact.indexOf(":"));
          const [src, dst] = fact.slice(fact.indexOf(":") + 1).split("->");
          return (
            <div key={fact} className="space-y-1">
              {((f.closed as string[]) ?? []).map((old) => (
                <div key={old} className="flex flex-wrap items-center gap-1.5">
                  <EntityChip id={old} struck onOpen={c.onOpen} onHover={c.onHover} />
                  <span className="font-mono text-[11px] text-ink-3 line-through">{rel}</span>
                  <EntityChip id={dst} struck onOpen={c.onOpen} onHover={c.onHover} />
                  <Chip tone="warn">valid_to set</Chip>
                </div>
              ))}
              <div className="flex flex-wrap items-center gap-1.5">
                <EntityChip id={src} onOpen={c.onOpen} onHover={c.onHover} />
                <span className="font-mono text-[11px] font-semibold text-ink-2">{rel}</span>
                <EntityChip id={dst} onOpen={c.onOpen} onHover={c.onHover} />
                <Chip tone={f.action === "created" ? "ok" : "warn"}>{str(f.action)}</Chip>
              </div>
            </div>
          );
        })}
        {d.document ? <Row k="Source"><EntityChip id={str(d.document)} onOpen={c.onOpen} onHover={c.onHover} /></Row> : null}
        {arr(impact.proposed_actions).length > 0 && (
          <Row k="Action">
            {arr(impact.proposed_actions).map((a) => <Chip key={str(a.id)} tone={toneOf(str(a.status))}>{str(a.kind)} · {str(a.status)}</Chip>)}
            <button onClick={c.onApprovals} className="text-xs font-medium text-accent hover:underline">Review</button>
          </Row>
        )}
      </Box>
    );
  },

  propose_action: (d, c) => (
    <Box title="Action" track="01">
      <Row k={str(d.kind)}>
        <EntityChip id={str(d.target)} onOpen={c.onOpen} onHover={c.onHover} />
        <Chip tone={toneOf(str(d.status))}>{str(d.status)}</Chip>
        {((d.blocked_by as string[]) ?? []).map((b) => <EntityChip key={b} id={b} onOpen={c.onOpen} onHover={c.onHover} />)}
        {d.status === "proposed" && <button onClick={c.onApprovals} className="text-xs font-medium text-accent hover:underline">Review</button>}
      </Row>
    </Box>
  ),

  handoff: (d, c) => (
    <Box title="Handoff" track="02">
      <Row k={str(d.status) || "open"}>
        {d.id ? <EntityChip id={str(d.id)} onOpen={c.onOpen} onHover={c.onHover} /> : null}
        {d.to ? <EntityChip id={str(d.to)} onOpen={c.onOpen} onHover={c.onHover} /> : null}
        {d.about ? <EntityChip id={str(d.about)} onOpen={c.onOpen} onHover={c.onHover} /> : null}
        <button onClick={c.onApprovals} className="text-xs font-medium text-accent hover:underline">Open</button>
      </Row>
    </Box>
  ),
};

/** The last result of each tool that has a renderer, in step order. */
export default function Callouts({ steps, ...ctx }: { steps: Step[] } & Ctx) {
  const last = new Map<string, Step>();
  steps.forEach((s) => { if (s.ok && s.data && RENDER[s.tool]) last.set(s.tool, s); });
  if (!last.size) return null;
  return (
    <div className="space-y-2">
      {[...last.values()].map((s) => <div key={s.tool}>{RENDER[s.tool](s.data as Rec, ctx)}</div>)}
    </div>
  );
}

export { svcId };
