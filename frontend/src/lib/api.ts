// Typed client for the Triveni FastAPI backend. Every result carries provenance.
export const API = process.env.NEXT_PUBLIC_TRIVENI_API ?? "http://localhost:8000";

export type Track = "01" | "02" | "03";

export interface PathRef {
  nodes: string[];
  edges: string[]; // "TYPE:src->dst"
  superseded?: boolean;
  stale?: boolean;
}

export interface ToolResult {
  data: Record<string, unknown>;
  cypher: string;
  params: Record<string, unknown>;
  paths: PathRef[];
  explanation: string;
  tracks: Track[];
  sources: string[];
  outcome?: Outcome;
  resolved?: Resolution[];
}

/** Every tool result states what happened, so an empty traversal is never read as "nothing is affected". */
export type Outcome = "answered" | "from_memory" | "not_in_graph" | "unknown_entity" | "recorded" | "refused" | "error" | "";

/** How a typed name was matched to a graph node before the tool ran ("Priya" -> per:priya-nair, partial_name). */
export interface Resolution {
  argument: string;
  query: string;
  id: string;
  name: string;
  label: string;
  how: "id" | "name" | "normalized" | "partial_name";
}

/** Set when the model's draft named something no tool returned: the draft is replaced by the tool results. */
export interface Guard {
  reason: string;
  draft: string;
}

export interface Step {
  tool: string;
  input: Record<string, unknown>;
  why: string;
  ok: boolean;
  explanation: string;
  tracks: Track[];
  sources: string[];
  cypher: string;
  params: Record<string, unknown>;
  paths: PathRef[];
  ms: number;
  via: string;
  data?: Record<string, unknown>; // the tool's result data (agent steps and direct runs)
  outcome?: Outcome;
  resolved?: Resolution[];
}

export interface Verification {
  verdict: "verified" | "partially_verified" | "unverified" | "no_citations";
  cited: number;
  grounded: string[];
  unbacked: string[];
  unknown: string[];
}

/** Live status of a running /api/ask call: which provider is being tried, which tool is running, fallbacks. */
export interface ProgressEvent {
  t: number; // seconds since the request started
  msg: string;
}

export interface AskProgress {
  run_id: string;
  done: boolean;
  events: ProgressEvent[];
}

export interface Health {
  falkordb: boolean;
  agent: boolean;
  providers: string[]; // tried in order; "rules" = no model
  model_backed: boolean;
  demo_replay?: boolean;
}

export interface AgentResult {
  question: string;
  tenant: string;
  answer: string;
  steps: Step[];
  model: string;
  fallbacks: string[];
  conversation_id: string;
  episode: string;
  verification: Verification;
  guard?: Guard | Record<string, never>;
  tracks: Track[];
  sources: string[];
}

export interface ConversationInfo {
  id: string;
  user_id: string;
  started_ts: string;
  messages: number;
  last_ts: string | null;
  title: string;
}

export interface HandoffInfo {
  id: string; ts: string; status: string; payload: { summary?: string; request?: string };
  from: string; to: string; incident: string | null; claimed_by: string | null; result: string | null;
}

export interface ActionInfo {
  id: string; kind: string; status: string; ts: string; args: Record<string, unknown>; proposed_by: string;
  target: string; blocked_by: string[]; approved_by: string | null; outbox: string | null;
}

export interface ToolInfo {
  name: string;
  description: string;
  input_schema: { properties: Record<string, SchemaProp>; required?: string[] };
  tracks: Track[];
  read_only: boolean;
}

export interface SchemaProp {
  type?: string;
  enum?: (string | number)[];
  default?: unknown;
  description?: string;
}

export interface GraphNode {
  id: string;
  label: string;
  name: string;
  tier?: number | null;
  kind?: string | null;
  status?: string | null;
}

export interface GraphEdge {
  type: string;
  source: string;
  target: string;
  superseded?: boolean;
  stale?: boolean;
}

export interface NodeEdge {
  type: string;
  out: boolean; // true: this node -> other
  id: string;
  label: string;
  name: string;
  valid_from: string | null;
  valid_to: string | null;
  source_doc: string | null;
}

export interface NodeDetail {
  id: string;
  label: string;
  properties: Record<string, unknown>;
  edges: NodeEdge[];
}

export interface Person {
  id: string;
  name: string;
  role: string | null;
}

export interface Doc {
  id: string;
  title: string;
  kind: string;
  ts: string;
  source: string;
  text: string;
  author: string | null;
  mentions: string[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => call<Health>("/api/health"),
  tenants: () => call<string[]>("/api/tenants"),
  tools: () => call<ToolInfo[]>("/api/tools"),
  runTool: (tenant: string, name: string, args: Record<string, unknown>) =>
    call<ToolResult>(`/api/tools/${name}`, { method: "POST", body: JSON.stringify({ tenant, args }) }),
  ask: (tenant: string, question: string, conversation_id?: string | null, run_id?: string, signal?: AbortSignal) =>
    call<AgentResult>("/api/ask", { method: "POST", signal,
      body: JSON.stringify({ tenant, question, conversation_id: conversation_id ?? null, run_id: run_id ?? null }) }),
  askProgress: (run_id: string) => call<AskProgress>(`/api/ask/progress/${encodeURIComponent(run_id)}`),
  conversations: (tenant: string) =>
    call<ConversationInfo[]>(`/api/conversations?tenant=${encodeURIComponent(tenant)}`),
  conversation: (tenant: string, id: string) =>
    call<{ id: string; messages: { role: string; text: string; seq: number; ts: string }[] }>(
      `/api/conversations/${encodeURIComponent(id)}?tenant=${encodeURIComponent(tenant)}`),
  ingest: (tenant: string, path: string) =>
    call<ToolResult>("/api/ingest", { method: "POST", body: JSON.stringify({ tenant, path }) }),
  handoffs: (tenant: string) => call<HandoffInfo[]>(`/api/handoffs?tenant=${encodeURIComponent(tenant)}`),
  actions: (tenant: string) => call<ActionInfo[]>(`/api/actions?tenant=${encodeURIComponent(tenant)}`),
  decide: (tenant: string, id: string, person: string, approve: boolean) =>
    call<{ id: string; status: string; outbox?: string; delivered_to?: string }>(
      `/api/actions/${encodeURIComponent(id)}/decide`, { method: "POST", body: JSON.stringify({ tenant, person, approve }) }),
  runRemediation: (tenant: string) =>
    call<{ handoff: { id: string; incident: string } | null; result: AgentResult | null }>(
      "/api/remediation/run", { method: "POST", body: JSON.stringify({ tenant }) }),
  overview: (tenant: string) =>
    call<{ nodes: GraphNode[]; edges: GraphEdge[] }>(`/api/graph/overview?tenant=${encodeURIComponent(tenant)}`),
  nodes: (tenant: string, ids: string[]) =>
    call<GraphNode[]>("/api/graph/nodes", { method: "POST", body: JSON.stringify({ tenant, ids }) }),
  node: (tenant: string, id: string) =>
    call<NodeDetail>(`/api/graph/node/${encodeURIComponent(id)}?tenant=${encodeURIComponent(tenant)}`),
  expand: (tenant: string, id: string, depth: 1 | 2) =>
    call<{ nodes: GraphNode[]; edges: GraphEdge[] }>(
      `/api/graph/expand/${encodeURIComponent(id)}?tenant=${encodeURIComponent(tenant)}&depth=${depth}`),
  people: (tenant: string) => call<Person[]>(`/api/people?tenant=${encodeURIComponent(tenant)}`),
  document: (tenant: string, id: string) =>
    call<Doc>(`/api/documents/${encodeURIComponent(id)}?tenant=${encodeURIComponent(tenant)}`),
};

/** "OWNS:team:payments->svc:payments-api" -> {type, source, target}. Ids contain ":" so split on the first one. */
export function parseEdge(ref: string): GraphEdge {
  const i = ref.indexOf(":");
  const [source, target] = ref.slice(i + 1).split("->");
  return { type: ref.slice(0, i), source, target };
}

/** Wrap a direct tool run as a one-step result so the UI renders tools and agent answers the same way. */
export function toolAsStep(name: string, input: Record<string, unknown>, r: ToolResult, ms: number): Step {
  return { tool: name, input, why: "", ok: true, explanation: r.explanation, tracks: r.tracks,
           sources: r.sources, cypher: r.cypher, params: r.params, paths: r.paths, ms, via: "http", data: r.data,
           outcome: r.outcome, resolved: r.resolved };
}
