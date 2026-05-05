/** Thin fetch wrapper that attaches X-User-Id / X-User-Role headers. */

export interface IdentityHeaders {
  "X-User-Id": string;
  "X-User-Role": string;
}

export function identityHeaders(userId: string, role: string): IdentityHeaders {
  return { "X-User-Id": userId, "X-User-Role": role };
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(
  path: string,
  opts: RequestInit & { userId: string; role: string },
): Promise<T> {
  const { userId, role, headers, ...rest } = opts;
  const res = await fetch(path, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...identityHeaders(userId, role),
      ...(headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = (body as { detail?: string }).detail ?? detail;
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
