/** SSE client for /api/chat/stream.
 *
 * Native EventSource only does GET. We use @microsoft/fetch-event-source
 * which supports POST + custom headers + abort.
 */
import { fetchEventSource } from "@microsoft/fetch-event-source";

import { identityHeaders } from "./client";

export type ChatStreamEvent =
  | { type: "open"; trace_id: string }
  | { type: "node"; payload: Record<string, unknown> }
  | { type: "delta"; text: string }
  | {
      type: "done";
      trace_id: string;
      final_message: string;
      report?: string | null;
      sql?: string | null;
      saveable: boolean;
    }
  | { type: "error"; error: string; trace_id?: string };

interface StreamOpts {
  userId: string;
  role: string;
  question: string;
  onEvent: (e: ChatStreamEvent) => void;
  signal?: AbortSignal;
}

export async function streamChat({ userId, role, question, onEvent, signal }: StreamOpts) {
  await fetchEventSource("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...identityHeaders(userId, role),
    },
    body: JSON.stringify({ question }),
    signal,
    openWhenHidden: true,
    onmessage(ev) {
      const data = ev.data ? safeParse(ev.data) : {};
      switch (ev.event) {
        case "open":
          onEvent({ type: "open", trace_id: (data as { trace_id?: string }).trace_id ?? "" });
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
            final_message: (data as { final_message?: string }).final_message ?? "",
            report: (data as { report?: string }).report,
            sql: (data as { sql?: string }).sql,
            saveable: Boolean((data as { saveable?: boolean }).saveable),
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
