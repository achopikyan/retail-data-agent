"""Read a per-session JSONL replay file."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src import settings
from src.api.schemas import SessionEvent, SessionResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str, trace_id: Optional[str] = Query(default=None)
) -> SessionResponse:
    path: Path = settings.LOG_DIR / f"session_{session_id}.jsonl"
    if not path.exists():
        # Allow callers to pass the literal filename too.
        alt = settings.LOG_DIR / session_id
        if alt.exists():
            path = alt
        else:
            raise HTTPException(404, f"no session log for {session_id}")

    events: list[SessionEvent] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if trace_id and not (rec.get("trace_id") or "").startswith(trace_id):
                continue
            extras = {
                k: v
                for k, v in rec.items()
                if k not in {"ts", "session_id", "event", "trace_id", "node", "latency_ms"}
            }
            events.append(
                SessionEvent(
                    ts=rec.get("ts", 0.0),
                    event=rec.get("event", "?"),
                    trace_id=rec.get("trace_id"),
                    node=rec.get("node"),
                    latency_ms=rec.get("latency_ms"),
                    extras=extras,
                )
            )
    return SessionResponse(session_id=session_id, events=events)
