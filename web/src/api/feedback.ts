import { api } from "./client";
import { FeedbackStats } from "./types";

export const submitFeedback = (
  auth: { userId: string; role: string },
  body: { trace_id: string; vote: "up" | "down" },
) =>
  api<void>(`/api/feedback`, {
    method: "POST",
    body: JSON.stringify(body),
    ...auth,
  });

export const feedbackStats = (auth: { userId: string; role: string }) =>
  api<FeedbackStats>(`/api/feedback/stats`, { method: "GET", ...auth });
