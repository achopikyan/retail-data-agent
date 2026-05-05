import { api } from "./client";
import { Persona, PersonasResponse } from "./types";

export const listPersonas = (auth: { userId: string; role: string }) =>
  api<PersonasResponse>(`/api/personas`, { method: "GET", ...auth });

export const activePersona = (auth: { userId: string; role: string }) =>
  api<Persona>(`/api/personas/active`, { method: "GET", ...auth });
