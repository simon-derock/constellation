import type { GraphEdge, GraphNode } from "../graph/types";
import type { Interval } from "./ownership";

export type Kind = "PERSPECTIVE" | "COUNTERFACTUAL" | "SILENCE";

export interface ProofQuery {
  name: string;
  params: Record<string, unknown>;
  sha256: string;
}

export interface Trace {
  stop_reason: string;
  strategy_changes: string[];
  llm_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  tools: { tool: string; args: Record<string, unknown>; artifacts: number; latency_ms: number }[];
}

export interface AskRequest {
  tenant: string;
  kind: Kind;
  question: string;
  actor?: string;
  day?: number;
}

export interface AskResponse {
  tenant: string;
  kind: Kind;
  answer: Record<string, unknown>;
  proof: { queries: ProofQuery[] };
  trace: Trace;
}

export interface ReplayResponse {
  all_match: boolean;
  results: { name: string; match: boolean; sha256: string }[];
}

export interface RunSummary {
  questions: number;
  accuracy: number;
  combined_score: number;
  violation_rate: number;
  violation_adjusted_combined_score: number;
  by_track: Record<string, number>;
  model: string;
  ledger?: string;
}

export interface Suggestion {
  kind: string;
  title: string;
  body: string;
  payload_hash: string;
  evidence: ProofQuery[];
}

export interface ActionRecord {
  id: string;
  kind: string;
  title: string;
  body: string;
  status: "proposed" | "approved" | "rejected" | "executing" | "executed" | "failed";
  approver: string | null;
  mode: "dry-run" | "real" | null;
  result: Record<string, unknown> | null;
  evidence: ProofQuery[];
  created: string;
}

export interface LiveStateRow {
  kind: string;
  state: string;
  items: number;
}

export interface LiveChange {
  item: string;
  title: string;
  predicate: "state" | "assignees" | "labels";
  old: string;
  new: string;
  at: number;
}

export interface LiveResponse {
  summary: LiveStateRow[];
  as_of: LiveStateRow[] | null;
  changes: LiveChange[];
  repos: { repo: string; items: number }[];
  freshness: { newest: string | null; repositories: number };
  proof: { queries: ProofQuery[] };
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const base = import.meta.env.VITE_API_URL ?? "";

// what a person should read for each failure; the server's own sentence is kept when it is already plain
function explain(status: number, detail: string): string {
  if (status === 403) return "That needs the operator key, and the key was not accepted.";
  if (status === 409) return "This action was already decided, so it cannot be decided again.";
  if (status === 429) return "Too many questions in a short time. Please wait a moment and ask again.";
  if (status === 503 && detail) return detail;
  if (status === 422) return `That could not be asked: ${detail || "the question was not accepted"}.`;
  return detail || `The server answered with an error (${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, init);
  } catch {
    throw new ApiError(0, "Could not reach the server. Check your connection and try again.");
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof body === "object" && body !== null && "detail" in body ? String(body.detail) : "";
    throw new ApiError(response.status, explain(response.status, detail));
  }
  return body as T;
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const ask = (body: AskRequest) => request<AskResponse>("/api/v1/ask", post(body));
export const replay = (body: { tenant: string; queries: ProofQuery[] }) =>
  request<ReplayResponse>("/api/v1/replay", post(body));
export const actors = (tenant: string) =>
  request<{ actors: { name: string; role: string }[] }>(`/api/v1/actors?tenant=${encodeURIComponent(tenant)}`);
export const ownership = (tenant: string) =>
  request<{ domains: { domain: string; intervals: Interval[] }[]; proof: { queries: ProofQuery[] } }>(
    `/api/v1/ownership?tenant=${encodeURIComponent(tenant)}`,
  );
export const live = (tenant: string, at?: number) =>
  request<LiveResponse>(`/api/v1/live?tenant=${encodeURIComponent(tenant)}${at === undefined ? "" : `&at=${at}`}`);
export interface GraphViewMeta {
  id: string;
  title: string;
  hint: string;
  tenant: string;
}

export const graphViews = () => request<{ views: GraphViewMeta[] }>("/api/v1/graph/views");
export const graphView = (view: string) =>
  request<{ view: GraphViewMeta; nodes: GraphNode[]; edges: GraphEdge[]; proof: { queries: ProofQuery[] } }>(
    `/api/v1/graph?view=${encodeURIComponent(view)}`,
  );
export interface SearchHit {
  item: string;
  title: string;
  repo: string;
  via: string[];
}

export const liveSearch = (q: string) =>
  request<{ hits: SearchHit[]; vector_used: boolean; proof: { queries: ProofQuery[] } }>(
    `/api/v1/live/search?tenant=falkordb&q=${encodeURIComponent(q)}`,
  );
export const livePeople = () =>
  request<{
    central: { person: string; score: number }[];
    bridges: { person: string; score: number }[];
    components: { size: number; components: number }[];
    proof: { queries: ProofQuery[] };
  }>("/api/v1/live/people?tenant=falkordb");
export const scoreboard = () => request<{ runs: RunSummary[] }>("/api/v1/scoreboard");

export const suggestions = (tenant: string) =>
  request<{ suggestions: Suggestion[] }>(`/api/v1/actions/suggestions?tenant=${encodeURIComponent(tenant)}`);
export const actionList = () => request<{ actions: ActionRecord[] }>("/api/v1/actions");
export const proposeAction = (tenant: string, payloadHash: string) =>
  request<ActionRecord>("/api/v1/actions", post({ tenant, payload_hash: payloadHash }));

// the operator key travels as a header and only for real approvals; a dry run never needs it
export const approveAction = (id: string, mode: "dry-run" | "real", operatorKey?: string) =>
  request<ActionRecord>(`/api/v1/actions/${encodeURIComponent(id)}/approve`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(mode === "real" && operatorKey ? { "x-approver-key": operatorKey } : {}),
    },
    body: JSON.stringify({ mode }),
  });
