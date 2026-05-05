import { api } from "./client";
import { DeleteMatchingRequest, DeleteResponse, Report } from "./types";

export const listReports = (auth: { userId: string; role: string }, all = false) =>
  api<Report[]>(`/api/reports${all ? "?all=true" : ""}`, { method: "GET", ...auth });

export const getReport = (auth: { userId: string; role: string }, id: number) =>
  api<Report>(`/api/reports/${id}`, { method: "GET", ...auth });

export const saveReport = (
  auth: { userId: string; role: string },
  body: { title: string; body: string },
) =>
  api<Report>(`/api/reports`, {
    method: "POST",
    body: JSON.stringify(body),
    ...auth,
  });

export const deleteReport = (
  auth: { userId: string; role: string },
  id: number,
  reason = "",
) =>
  api<DeleteResponse>(
    `/api/reports/${id}?confirm=yes&reason=${encodeURIComponent(reason)}`,
    { method: "DELETE", ...auth },
  );

export const deleteMatching = (
  auth: { userId: string; role: string },
  req: DeleteMatchingRequest,
) =>
  api<DeleteResponse>(`/api/reports/delete-matching`, {
    method: "POST",
    body: JSON.stringify(req),
    ...auth,
  });

/** Used to compute the "expected_count" for cross-user GDPR deletes. */
export const previewMatching = async (
  auth: { userId: string; role: string },
  substring: string,
): Promise<{ count: number; ids: number[]; cross_user: boolean }> => {
  const all = auth.role === "gdpr_officer";
  const reports = await listReports(auth, all);
  const needle = substring.toLowerCase();
  const matches = reports.filter(
    (r) =>
      r.title.toLowerCase().includes(needle) || r.body.toLowerCase().includes(needle),
  );
  const cross_user = matches.some((r) => r.owner_id !== auth.userId);
  return { count: matches.length, ids: matches.map((r) => r.id), cross_user };
};
