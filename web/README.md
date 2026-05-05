# Web Frontend (React + TypeScript)

A React SPA that exposes every CLI capability as a polished web UI: streaming chat, saved reports, audit log, GDPR cross-user delete, per-user preferences, persona viewer.

The frontend has **no business logic** — it consumes the FastAPI server in `src/api/`, which thinly wraps the existing `src/tools/*` and `src/graph/*` modules. PII masking, ownership enforcement, self-heal, and the audit trail all live server-side.

## Stack

- **Vite** + **React 18** + **TypeScript**
- **Tailwind CSS** for styling (no heavyweight component library)
- **TanStack Query** for server-state caching
- **React Router v6** for tab navigation
- **`@microsoft/fetch-event-source`** for streaming the chat endpoint (POST + headers — native `EventSource` is GET-only)
- **`react-markdown`** + `remark-gfm` for rendering agent reports

## Auth model — header-based, no real auth

Every request attaches `X-User-Id` and `X-User-Role` headers. Switch user/role via the dropdown in the header; choices persist to `localStorage`.

This **mirrors the CLI's `/login`**. There is no password and no session token — a reviewer can spoof any user. That's fine for a local prototype; real OAuth would slot in at the FastAPI `get_identity` dependency without changing any view code.

## Local dev

Two terminals:

```bash
# 1. Backend (port 8000)
make api

# 2. Frontend (port 5173)
make web
```

Vite proxies `/api → :8000`, so the browser only knows about port 5173.

Open <http://localhost:5173>.

## Docker (one command)

```bash
docker compose up --build
```

This starts both services. The web container's nginx proxies `/api` to the api container — same browser URL (`http://localhost:5173`), production-style serving.

## Production migration

- Real auth at the `get_identity` FastAPI dependency.
- Replace nginx proxy with a real edge (Cloud Run + IAP, or Vercel + a public API URL).
- Add CSRF tokens and tighten CORS in `src/api/main.py`.
- Persist user picker preference server-side once auth exists.
