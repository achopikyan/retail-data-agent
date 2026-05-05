import { api } from "./client";
import { PrefsOut } from "./types";

export const getPrefs = (auth: { userId: string; role: string }) =>
  api<PrefsOut>(`/api/prefs`, { method: "GET", ...auth });

export const setPref = (
  auth: { userId: string; role: string },
  body: { key: string; value: string },
) =>
  api<PrefsOut>(`/api/prefs`, {
    method: "PUT",
    body: JSON.stringify(body),
    ...auth,
  });

export const allowedKeys = (auth: { userId: string; role: string }) =>
  api<string[]>(`/api/prefs/allowed-keys`, { method: "GET", ...auth });
