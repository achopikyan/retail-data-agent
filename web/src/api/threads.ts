/** Thread CRUD client. */
import { api } from "./client";

export interface Thread {
  thread_id: string;
  title: string | null;
  created_at: number;
  updated_at: number;
  last_message_at: number | null;
  archived: boolean;
}

export interface ThreadsListResponse {
  threads: Thread[];
}

interface Identity {
  userId: string;
  role: string;
}

export function listThreads(
  ident: Identity,
  archived = false,
): Promise<ThreadsListResponse> {
  const q = archived ? "?archived=true" : "";
  return api(`/api/threads${q}`, { ...ident, method: "GET" });
}

export function createThread(
  ident: Identity,
  title?: string,
): Promise<Thread> {
  return api("/api/threads", {
    ...ident,
    method: "POST",
    body: JSON.stringify({ title: title ?? null }),
  });
}

export function updateThread(
  ident: Identity,
  threadId: string,
  patch: { title?: string; archived?: boolean },
): Promise<Thread> {
  return api(`/api/threads/${threadId}`, {
    ...ident,
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteThread(
  ident: Identity,
  threadId: string,
): Promise<{ deleted: string }> {
  return api(`/api/threads/${threadId}`, {
    ...ident,
    method: "DELETE",
  });
}

export interface ThreadMessage {
  role: "user" | "assistant";
  content: string;
  created_at: number;
  trace_id: string | null;
  turn_idx: number;
}

export interface ThreadMessagesResponse {
  thread_id: string;
  title: string | null;
  messages: ThreadMessage[];
}

export function getThreadMessages(
  ident: Identity,
  threadId: string,
): Promise<ThreadMessagesResponse> {
  return api(`/api/threads/${threadId}/messages`, {
    ...ident,
    method: "GET",
  });
}
