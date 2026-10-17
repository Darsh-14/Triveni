# Triveni UI/UX plan

Status: rev 2, awaiting approval (Oct 17).
Decided: light theme with tokens ready for dark · deps `lucide-react` + `cytoscape-fcose` (directed chains use Cytoscape's built-in `breadthfirst`) · Evidence mode shows evidence nodes only.
Rev 2 changes: layout and components taken from reference products (Section 2) · no descriptive text anywhere in the UI (Section 3).
Scope: frontend only (`frontend/`), except items marked **(API)**. Constraints: one framework (Next.js + Tailwind + Cytoscape), no mobile layout, no auth, no decorative animation (cut list), feature freeze Oct 18 10:00 IST.

"Copy" here means copying layout, component anatomy and interaction patterns. We do not copy logos, brand marks, product names, proprietary icons or source code.

---

## 1. Users and the one-line goal

| User | Must be able to, without help |
|---|---|
| On-call engineer | Get impact, owner to page, last change, prior fix, safe next action, on one screen |
| Engineering manager | See single points of knowledge, orphaned services, decision history |
| Hackathon judge (3–5 min, cold) | Find their track's scenario, run it, see the path that proves the answer |
| Video viewer (1080p) | Read every label; follow one highlighted path at a time |

Goal: **question → answer → proof → action, with the graph as the proof.**

---

## 2. Reference products and what we take from each

| Product | Why it is relevant | What we copy |
|---|---|---|
| **FalkorDB Browser** (the sponsor's own graph UI) | Same database, same judges | Narrow left icon sidebar · top bar with graph selector · **Graph / Table** tabs over the results · canvas control bar: zoom in, zoom out, fit, layout **Force / Tree / Radial**, **Dim** (fade outside selection) · **Labels** and **Relationships** toggle lists that filter without re-running · resizable, context-driven **right panel** (Data panel on node select) |
| **Perplexity / Glean** (answers with sources) | Triveni's answers must cite sources | Question as the card heading · **source cards row above the answer** · **inline citation chips** inside the answer text · tools used collapsed into one chip ("3 tools") · composer pinned at the bottom, follow-ups in the same thread |
| **incident.io Investigations** | AI incident investigation, our core use case | A **headline conclusion** first, then findings · a **confidence label** per answer (single word, not a score) · every finding linked to its evidence · contradicted items kept and marked, not hidden (our superseded decisions and stale runbooks) |
| **Datadog Bits AI SRE** | AI SRE agent with visible steps | **Investigation steps** list while running, collapsed to a summary when done · hypothesis status words **validated / invalidated / inconclusive** → our proof-check verdict words · an "Agent trace" of tools called, data queried |
| **Neo4j Bloom** | Business-user graph exploration | **Search overlay on the canvas** to find and focus a node · **legend panel** overlay listing categories present · the scene shows only what search/exploration found (= our Evidence mode) · per-category node styling |
| **Linear / Vercel (Geist)** | Data-dense developer tools | Hairline borders, almost no shadow, one accent, density from type scale · Geist Sans/Mono |

Rules backing these choices (from rev 1 research, kept): Nielsen's heuristics (status visibility, consistency, recognition over recall, minimalist design, error prevention); agent UX (show steps, a confidence signal, an action audit, approvals that show the resolved action); Shneiderman (overview → zoom/filter → details on demand); WCAG 2.2 AA (contrast 4.5:1 text and 3:1 marks, focus visible, never colour alone).

---

## 3. Content rule: no descriptive text

The UI shows **data, labels and controls only**. No sentences that explain what a feature does, what a step means, or what to do next. The README and the demo video carry the explanation.

Allowed: nouns and short labels ("Handoffs", "Sources", "Approve"), entity names and ids, numbers, status words ("verified", "blocked"), the agent's own answer text, error messages (shortened to the fact plus the command to run), `title` tooltips on icon-only buttons.

### Strings removed from the current UI

| Where | Remove | Replace with |
|---|---|---|
| [Triveni.tsx](../frontend/src/components/Triveni.tsx) header | "engineering Company Brain on FalkorDB · every answer proves its path" | nothing |
| Triveni.tsx empty feed | "Pick a scenario above. Each answer shows the tools used…" | the scenario grid (no captions) |
| Triveni.tsx composer placeholder | "Ask about services, owners, incidents, decisions…" / "Agent offline: use the scenarios or Run a tool" | "Ask" / "Agent offline" |
| Triveni.tsx tabs | "Ask the agent" / "Run a tool" / "Handoffs & approvals" | sidebar icons with labels "Ask", "Tools", "Approvals" |
| Triveni.tsx status tooltip | "Providers are tried in order; rules = keyword planner…" | provider names only |
| [EntryCard.tsx](../frontend/src/components/EntryCard.tsx) pending | "Agent is working" / "Running the tool on the graph" / "Extracting facts and merging them into the graph" | spinner + current tool name + elapsed |
| EntryCard.tsx pending | the elapsed list of progress sentences | step chips (`owner_of ✓`, `blast_radius …`) |
| EntryCard.tsx pending | "Free-tier models can be slow or rate limited; Triveni falls back…" | nothing (the fallback shows as a provider chip) |
| EntryCard.tsx steps | `why: …` line and the `explanation` line under every step | nothing (one-line step row: # · tool · args · ms · Cypher) |
| EntryCard.tsx proof badge | tooltip "Checked by code, not a model…", prefixes "not shown by a tool:" / "not in the graph:" | verdict word + `n/m` + id chips coloured by status |
| EntryCard.tsx footer | "model: …" / "memory: …" sentences | provider chip, episode chip |
| [Drawer.tsx](../frontend/src/components/Drawer.tsx) Cypher | the step explanation paragraph; "Values are always passed as parameters…" | query + params only |
| [Coordination.tsx](../frontend/src/components/Coordination.tsx) headings | "(graph nodes, the only channel between agents)", "(need a human; blocked when a current decision forbids them)" | "Handoffs", "Actions" |
| Coordination.tsx empty states | "None yet. Ask scenario #6 to have triage hand off." / "No proposed actions." | "No handoffs" / "No actions" |
| Coordination.tsx notes | "… executed → … (outbox …)" sentences | status chip + outbox chip |
| [ToolRunner.tsx](../frontend/src/components/ToolRunner.tsx) | tool description paragraphs (if shown) | tool name + parameter fields |
| Scenario list | long question labels as button text stay (they are the question), no captions | — |

Rev 1 items dropped by this rule: start-screen heading, "Shows: …" captions on scenario cards, offline banner sentence, tenant-switch toast sentence, header subtitle, parameterisation note.

The provenance contract still returns `explanation`. The UI no longer prints it; it stays in the API and in the Table view's raw data.

---

## 4. Layout (FalkorDB Browser frame + Perplexity thread + Bloom overlays)

```
┌──┬───────────────────────────────────────────────────────────────────────────────┐
│  │ Top bar: Triveni · [tenant ▾ tenant_acme] · ● Graph · ● groq → gemini → rules │
│S │          · Approvals (2) · Replay                                             │
│i ├────────────────────────┬──────────────────────────────────────┬───────────────┤
│d │ Thread (480px)         │ [Graph | Table]       title · counts │ Right panel   │
│e │  answer cards          │ ┌──────────────────────────────────┐ │ (resizable,   │
│b │  (Perplexity anatomy)  │ │ search overlay (Bloom)           │ │  on demand)   │
│a │                        │ │                                  │ │  Node         │
│r │                        │ │        canvas                    │ │  Cypher       │
│  │                        │ │                                  │ │  Source       │
│48│                        │ │ legend / Labels+Rels  controls   │ │  Approvals    │
│px│ composer (bottom)      │ │ (bottom-left)         (bottom-r) │ │               │
└──┴────────────────────────┴──────────────────────────────────────┴───────────────┘
```

- **Sidebar (48px icons, FalkorDB Browser)**: Scenarios · Conversations · Tools · Approvals (badge count). Each opens a flyout over the thread column. Icon + short label under it.
- **Top bar**: wordmark, tenant selector that shows the graph name, status pills (icon + word), Approvals count, Replay toggle **(API: `demo_replay` in /api/health)**.
- **Thread**: chronological, newest at the bottom, auto-scroll, composer pinned at the bottom. Empty thread = the scenario grid.
- **Centre**: `Graph | Table` tabs (FalkorDB Browser). Table lists the current nodes (label, name, id) and edges (type, from, to, `valid_to`).
- **Right panel (FalkorDB Browser Data panel)**: closed by default; opens on node click, Cypher, source, or Approvals; canvas re-fits; `Esc` closes.

---

## 5. Components

### 5.1 Scenario grid (empty thread / Scenarios flyout)
Three columns headed **01 Act**, **02 Remember**, **03 Company Brain**. Each tile: `#n` + the question. No captions.
- 01: #1 payments-api failing · #4 single points of knowledge · #6 hand off + approve
- 02: #5 recall after restart · #6 handoff · #8 tenant isolation
- 03: #2 retry-policy decision trail · #3 who is on call · #7 live ingest

### 5.2 Answer card (Perplexity + incident.io + Datadog anatomy)
1. **Question** as heading (16px semibold) · time.
2. **Verdict row**: confidence word (`Verified` / `Partly verified` / `Unverified` / `No citations`, from the deterministic proof check) · `5/5` · `3 tools` chip (expands step list) · `1.4 s` · provider chip · track tags.
3. **Sources row**: compact source cards (kind icon, id, title truncated), horizontal scroll. Click → right panel Source.
4. **Answer** (14px, ≤65ch). Entity ids in the text (`svc:…`, `per:…`, `adr:…`, `doc:…`) render as **inline citation chips** with a type icon; hover highlights on the canvas, click opens the Node panel.
5. **Data callouts** (no sentences, only fields):
   - Recalled · `ep:0012` · Oct 15 · `restart-workers` 3✓ 0✗ → 4✓  (02)
   - Page · person · role · `ON_CALL_FOR` path  (01/03)
   - No path · searched pattern (`(:Person)-[:ON_CALL_FOR]->(svc:billing-batch)`) · 0 rows · orphans list  (03)
   - Changed · ~~`team:core OWNS billing-batch`~~ `valid_to 2026-10-17` → `team:atlas OWNS billing-batch` · two source chips  (03)
   - Action · `create_ticket` → target · Approve / Reject, or `Blocked` · `adr:0007`  (01)
6. **Steps** (collapsed; Datadog Agent Trace style): one row per step `1 · blast_radius · {service} · 42 ms · Cypher`. Clicking a row highlights only that step's paths.
7. **Details** (collapsed): raw JSON, fallbacks, conversation and episode ids.

Pending: spinner · elapsed · a row of step chips that fill in as tools run (`owner_of ✓` `blast_radius …`) · Cancel. On completion it becomes row 6.

### 5.3 Graph canvas (FalkorDB Browser controls + Bloom overlays)
- One Cytoscape instance for the page lifetime; elements updated, never destroyed/rebuilt.
- **Controls bar (bottom-right)**: zoom +/−, fit, layout `Force` (fcose) / `Tree` (breadthfirst, directed) / `Radial` (concentric), `Dim` toggle. Default layout by tool: `blast_radius`, `decision_trail`, `shortest_path` → Tree; others → Force.
- **Labels / Relationships panel (bottom-left, Bloom legend + FalkorDB filters)**: types present, with shape, colour and count; click toggles visibility.
- **Search overlay (top-left, Bloom)**: type a name or id → focus and select the node.
- **Node style**: shape + colour per family (Service round-rectangle blue; Person ellipse / Team hexagon green; Deployment tag teal; Incident triangle red; Decision diamond amber; Document rectangle slate; memory/agent types violet octagon). Labels hidden below zoom 0.8.
- **Edges**: highlighted edges 2.5px with type label; superseded/stale dashed plus a `superseded` suffix.
- **Select**: click → right panel Node; `Dim` fades everything outside the selection and its neighbours.

### 5.4 Right panel
- **Node**: id (copy), label, properties table, current edges, historical edges (`valid_to`), sources.
- **Cypher**: tool name, highlighted query (small keyword highlighter), params table, Copy.
- **Source**: kind · author · ts header, document text, mentioned ids as chips.
- **Approvals**: Actions (proposed first): status chip · kind · target · args title · approver dropdown · Approve / Reject; blocked shows `Blocked` + decision chip. Handoffs: `open → claimed → done` stepper · from → to · incident chip. Button: "Run remediation".

---

## 6. Interaction and accessibility
- Keys: `/` composer · `Enter` send · `Esc` close panel · `1–8` scenario (empty thread) · `f` fit · `d` dim.
- 2px accent focus ring on every control; answer cards are `<article>` with real buttons.
- `aria-live="polite"` on the pending row.
- Text ≥ 12px (answers 14px); contrast 4.5:1 text, 3:1 graph marks; status always icon + word, never colour alone.

## 7. Visual system (Tailwind v4 `@theme` tokens in `globals.css`)
- Light theme; neutrals slate; surfaces `bg` / `panel` / `raised`; 1px hairlines; shadow only on the right panel.
- One indigo accent (primary button, focus, selected). Semantic colours used only for status: green verified/executed, amber partial/proposed/stale, red incident/blocked/error.
- Track tags: neutral outline `01 Act` · `02 Remember` · `03 Brain` with a glyph; track colour only as a thin left rule on callouts.
- Type: 12 / 13 / 14 / 16 / 20; Geist Sans, Geist Mono for ids, tools, Cypher. Spacing on a 4px grid. Icons from `lucide-react`.

## 8. Track visibility check
| Track | Visible as |
|---|---|
| 01 Act | `3 tools` steps chip + Cypher, algorithm results on canvas, Approvals badge, Blocked action with decision chip |
| 02 Remember | Conversations flyout restored from the graph, Recalled callout with counters, handoff stepper, tenant selector showing graph name |
| 03 Company Brain | Sources row on every answer, decision trail in Tree layout with superseded edges, No-path callout, Changed callout |

---

## 9. Build plan

| Phase | Content | Est. | Exit check |
|---|---|---|---|
| U1 Foundations + text purge | Tokens, type, focus ring, status pills, track tags, deps; remove every string in Section 3 | 1.5 h | No explanatory sentence left (grep); lint clean |
| U2 Frame | Sidebar + flyouts, top bar, chronological thread + bottom composer, scenario grid, Graph/Table tabs, right panel shell | 2.5 h | All 8 scenarios run from the grid and the flyout |
| U3 Answer card | Verdict row, sources row, inline citation chips, callouts, collapsed steps | 3 h | Scenarios 1, 2, 3, 5, 7 each show their callout |
| U4 Canvas | Single instance, controls bar (Force/Tree/Radial, Dim, fit, zoom), Labels/Relationships panel, search overlay, shapes, per-step highlight | 3 h | Step 2 click highlights only its path; no flicker |
| U5 Right panel + approvals | Node / Cypher / Source / Approvals, approver dropdown, top-bar count, handoff stepper, Table view | 2 h | Scenario 6 end-to-end from the Approvals badge |
| U6 QA | Keyboard, aria-live, 1080p check, judge dry run | 1 h | Section 10 passes |

Total ≈ 13 h. Cut order if short: search overlay, Radial layout, Table view, handoff stepper. Never cut the text purge, sources row, or the 02/03 callouts.

## 10. Checks
- Cold dry run: a new person runs one scenario per track in under 3 minutes and points to the proving path.
- `grep` the components for sentence-length string literals; each must be a label, a status word, data, or an error.
- 1920×1080 recording at 100% zoom; all labels readable paused at 720p.
- Keyboard-only Scenario 6; Lighthouse accessibility ≥ 95.
- `npm run lint`, `npm run build`, `pytest -q` unchanged.

## 11. Sources
- FalkorDB Browser — [overview](https://docs.falkordb.com/browser/), [Graph page](https://docs.falkordb.com/browser/ui/graph-page.md), [Graph canvas](https://docs.falkordb.com/browser/ui/graph-canvas.md)
- incident.io — [How investigations work](https://docs.incident.io/investigations/how-investigations-work), [ZenML case study](https://www.zenml.io/llmops-database/ai-powered-incident-response-system-with-multi-agent-investigation)
- Datadog Bits AI SRE — [Investigate issues](https://docs.datadoghq.com/bits_ai/bits_ai_sre/investigate_issues), [launch post](https://www.datadoghq.com/blog/bits-ai-sre/)
- Neo4j Bloom — [Explore overview](https://neo4j.com/docs/aura/explore/explore-visual-tour/explore-overview/), [visual tour](https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour), [Desktop Explore](https://neo4j.com/docs/desktop/current/explore/)
- Glean — [Assistant overview](https://www.gend.co/blog/glean-assistant-search-autocomplete-images-2026), [review](https://fritz.ai/glean-review/)
- AI SRE landscape — [Cleric vs Resolve vs Traversal](https://prommer.net/en/tech/guides/cleric-vs-resolve-ai-vs-traversal/), [Cleric launch](https://businesswire.com/news/home/20251209625361/en/Cleric-Launches-the-First-Self-Learning-AI-SRE)
- Agent UX — [Smashing Magazine, Feb 2026](https://smashingmagazine.com/2026/02/designing-agentic-ai-practical-ux-patterns/), [p0stman](https://p0stman.com/agent-ux), [Cloudscape thinking](https://cloudscape.design/patterns/genai/thinking/)
- Approvals — [Mastra](https://mastra.ai/blog/hitl-where-to-put-approval-in-agents-and-workflows), [Microsoft AG-UI](https://learn.microsoft.com/en-us/agent-framework/integrations/ag-ui/human-in-the-loop), [Cloudflare](https://developers.cloudflare.com/agents/concepts/agentic-patterns/human-in-the-loop/)
- Graph vis and heuristics — [Shneiderman 1996](https://webspace.science.uu.nl/~telea001/uploads/VACourse/Shneiderman96.pdf), [Cambridge Intelligence](https://cambridge-intelligence.com/getting-the-perfect-look-and-feel-for-your-network-visualizations/), [Nielsen heuristics summary](https://thedecisionlab.com/reference-guide/design/nielsens-heuristics)
- Incident dashboards — [OneUptime](https://oneuptime.com/blog/post/2026-08-06-first-15-minutes-incident-dashboard/view)
- Accessibility — [WCAG 1.4.11](https://www.disabilityworld.org/toolkit/standards/wcag/1-4-11-non-text-contrast/), [Yatil on focus](https://www.yatil.net/blog/wcag22-visible-focus)
- Visual language — [Vercel/Geist](https://blakecrosley.com/guides/design/vercel), [Linear notes](https://design.hagicode.com/designs/linear.app/)
