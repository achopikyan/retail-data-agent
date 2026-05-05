import { api } from "./client";
import { AuditEntry, SessionEvent } from "./types";

export const listAudit = (auth: { userId: string; role: string }, limit = 50) =>
  api<AuditEntry[]>(`/api/audit?limit=${limit}`, { method: "GET", ...auth });

export const getSession = async (
  auth: { userId: string; role: string },
  sessionId: string,
  traceId?: string,
): Promise<{ session_id: string; events: SessionEvent[] }> => {
  const q = traceId ? `?trace_id=${encodeURIComponent(traceId)}` : "";
  return api(`/api/sessions/${sessionId}${q}`, { method: "GET", ...auth });
};
