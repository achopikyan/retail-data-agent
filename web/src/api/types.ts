/** Shared TS types — mirror the Pydantic schemas in src/api/schemas.py. */

export interface ChatResponse {
  trace_id: string;
  final_message: string;
  report?: string | null;
  sql?: string | null;
  intent?: string | null;
  saveable: boolean;
}

export interface Report {
  id: number;
  owner_id: string;
  title: string;
  body: string;
  created_at: number;
  updated_at: number;
}

export interface AuditEntry {
  id: number;
  ts: number;
  actor_id: string;
  action: string;
  target_ids: string;
  reason: string | null;
  trace_id: string | null;
}

export interface FeedbackStats {
  total: number;
  up: number;
  down: number;
  promoted: number;
}

export interface PrefsOut {
  user_id: string;
  prefs: Record<string, string>;
}

export interface Persona {
  name: string;
  description: string;
  instructions: string;
}

export interface PersonasResponse {
  active: string;
  personas: Persona[];
}

export interface SessionEvent {
  ts: number;
  event: string;
  trace_id?: string | null;
  node?: string | null;
  latency_ms?: number | null;
  extras: Record<string, unknown>;
}

export interface DeleteResponse {
  deleted: number;
  target_ids: number[];
}

export interface DeleteMatchingRequest {
  substring: string;
  expected_count?: number;
  reason?: string;
}
