import type { Track } from "./api";

// Demo scenarios (MVP.md Section 5). With an agent the question goes to the model over MCP;
// without one the scenario's main tool runs directly, so the demo still works without a model.
export interface Scenario {
  n: number;
  label: string;
  question: string;
  tracks: Track[]; // columns of the scenario grid it appears in
  tool?: [string, Record<string, unknown>];
  ingest?: string;
  tenant?: string; // switch to this tenant first (scenario 8: isolation)
}

export const SCENARIOS: Scenario[] = [
  { n: 1, label: "payments-api is failing", question: "payments-api is failing, what's affected and who do I page?",
    tracks: ["01"], tool: ["blast_radius", { service: "payments-api" }] },
  { n: 4, label: "Single points of knowledge?", question: "Which engineers are single points of knowledge?",
    tracks: ["01"], tool: ["key_people", {}] },
  { n: 6, label: "Hand off inc:0057 to remediation",
    question: "inc:0057: orders-api p99 latency is above 4s and workers are saturated. Investigate briefly, then hand it off to remediation for a fix.",
    tracks: ["01", "02"], tool: ["similar_incidents", { incident: "inc:0057" }] },
  { n: 5, label: "orders-api slow again: seen this before?", question: "orders-api latency is spiking again. Have we seen this before, and what fixed it?",
    tracks: ["02"], tool: ["recall", { entities: ["svc:orders-api", "inc:0057"] }] },
  { n: 8, label: "Tenant beta: who owns payments-api?", question: "Who owns payments-api and who is on call?",
    tracks: ["02"], tool: ["owner_of", { service: "payments-api" }], tenant: "beta" },
  { n: 2, label: "Change retry policy on orders-api?", question: "Can we change the retry policy on orders-api?",
    tracks: ["03"], tool: ["decision_trail", { service: "orders-api", action: "change_retry_policy" }] },
  { n: 3, label: "Who is on call for billing-batch?", question: "Who is on call for billing-batch?",
    tracks: ["03"], tool: ["why_not", { kind: "on_call", service: "billing-batch" }] },
  { n: 7, label: "Ingest: billing-batch moves to Atlas", question: "Ingest #eng-announcements: billing-batch moves to Team Atlas",
    tracks: ["03"], ingest: "data/raw/live/chat-billing-move.md" },
  { n: 9, label: "What if Priya Nair leaves?", question: "What happens to our knowledge coverage if Priya Nair leaves?",
    tracks: ["03"], tool: ["what_if", { scenario: "person_leaves", entity: "per:priya-nair" }] },
];

export const TRACK_COLUMNS: { track: Track; title: string }[] = [
  { track: "01", title: "01 Act" },
  { track: "02", title: "02 Remember" },
  { track: "03", title: "03 Company Brain" },
];
