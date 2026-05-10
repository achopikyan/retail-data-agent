/** SSE client for /api/chat/stream.
 *
 * Native EventSource only does GET. We use @microsoft/fetch-event-source
 * which supports POST + custom headers + abort.
 */
import { fetchEventSource } from "@microsoft/fetch-event-source";

import { api, identityHeaders } from "./client";

export type ChatStreamEvent =
  | { type: "open"; trace_id: string; thread_id: string }
  | { type: "node"; payload: Record<string, unknown> }
  | { type: "delta"; text: string }
  | {
      type: "done";
      trace_id: string;
      thread_id: string;
      final_message: string;
      report?: string | null;
      sql?: string | null;
      saveable: boolean;
      intent?: string | null;
      raw_question?: string | null;
      rewritten_question?: string | null;
      history_used?: boolean;
      needs_clarification?: boolean;
      turn_count?: number;
      recovery_token?: string | null;
      refused_intent?: string | null;
      is_compound?: boolean;
      sub_questions?: string[] | null;
      sub_results?: SubResult[] | null;
    }
  | { type: "error"; error: string; trace_id?: string };

export interface SubResult {
  sub_question: string;
  sub_trace_id: string;
  sql?: string | null;
  report?: string | null;
  row_count: number;
  error?: string | null;
}

interface StreamOpts {
  userId: string;
  role: string;
  question: string;
  threadId?: string | null;
  onEvent: (e: ChatStreamEvent) => void;
  signal?: AbortSignal;
}

export async function streamChat({
  userId,
  role,
  question,
  threadId,
  onEvent,
  signal,
}: StreamOpts) {
  await fetchEventSource("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...identityHeaders(userId, role),
    },
    body: JSON.stringify({ question, thread_id: threadId ?? null }),
    signal,
    openWhenHidden: true,
    onmessage(ev) {
      const data = ev.data ? safeParse(ev.data) : {};
      switch (ev.event) {
        case "open":
          onEvent({
            type: "open",
            trace_id: (data as { trace_id?: string }).trace_id ?? "",
            thread_id: (data as { thread_id?: string }).thread_id ?? "",
          });
          break;
        case "node":
          onEvent({ type: "node", payload: data as Record<string, unknown> });
          break;
        case "delta":
          onEvent({ type: "delta", text: (data as { text?: string }).text ?? "" });
          break;
        case "done":
          onEvent({
            type: "done",
            trace_id: (data as { trace_id?: string }).trace_id ?? "",
            thread_id: (data as { thread_id?: string }).thread_id ?? "",
            final_message: (data as { final_message?: string }).final_message ?? "",
            report: (data as { report?: string }).report,
            sql: (data as { sql?: string }).sql,
            saveable: Boolean((data as { saveable?: boolean }).saveable),
            intent: (data as { intent?: string | null }).intent ?? null,
            raw_question: (data as { raw_question?: string }).raw_question,
            rewritten_question: (data as { rewritten_question?: string }).rewritten_question,
            history_used: Boolean((data as { history_used?: boolean }).history_used),
            needs_clarification: Boolean(
              (data as { needs_clarification?: boolean }).needs_clarification,
            ),
            turn_count: (data as { turn_count?: number }).turn_count,
            recovery_token: (data as { recovery_token?: string | null }).recovery_token ?? null,
            refused_intent: (data as { refused_intent?: string | null }).refused_intent ?? null,
            is_compound: Boolean((data as { is_compound?: boolean }).is_compound),
            sub_questions: (data as { sub_questions?: string[] | null }).sub_questions ?? null,
            sub_results: (data as { sub_results?: SubResult[] | null }).sub_results ?? null,
          });
          break;
        case "error":
          onEvent({
            type: "error",
            error: (data as { error?: string }).error ?? "unknown",
            trace_id: (data as { trace_id?: string }).trace_id,
          });
          break;
      }
    },
    onerror(err) {
      onEvent({ type: "error", error: String(err) });
      throw err; // stop reconnecting
    },
  });
}

function safeParse(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return {};
  }
}

// --- recovery from a router refusal --------------------------------------

export interface ChatRecoverResponse {
  trace_id: string;
  thread_id: string;
  final_message: string;
  report?: string | null;
  sql?: string | null;
  saveable: boolean;
  intent?: string | null;
  recovery_token?: string | null;
}

export async function recoverChat(args: {
  userId: string;
  role: string;
  recoveryToken: string;
  rawQuestion: string;
  threadId: string | null;
}): Promise<ChatRecoverResponse> {
  return api<ChatRecoverResponse>("/api/chat/recover", {
    userId: args.userId,
    role: args.role,
    method: "POST",
    body: JSON.stringify({
      recovery_token: args.recoveryToken,
      raw_question: args.rawQuestion,
      thread_id: args.threadId,
    }),
  });
}
