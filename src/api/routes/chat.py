"""Chat routes — POST /api/chat (non-streaming) and POST /api/chat/stream (SSE).

The SSE handler runs the LangGraph in a worker thread and forwards
events from a queue to the SSE response. A custom SessionLog subclass
pushes node-level events onto the same queue, so the client sees node
progress in real time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import uuid
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.api.deps import base_graph_resources, get_resources
from src.api.identity import Identity, get_identity
from src.api.schemas import ChatRequest, ChatResponse
from src.obs.log import SessionLog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


# --- non-streaming ---------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, identity: Identity = Depends(get_identity)) -> ChatResponse:
    res = get_resources()
    session_log = SessionLog()
    trace_id = uuid.uuid4().hex[:10]
    session_log.event(
        "turn_start",
        trace_id=trace_id,
        user=identity.user_id,
        role=identity.role,
        user_msg=req.question,
        source="api",
    )
    initial: Dict[str, Any] = {
        "question": req.question,
        "user_id": identity.user_id,
        "trace_id": trace_id,
        "sql_attempts": 0,
        "resources": base_graph_resources(session_log),
    }
    try:
        final = res.graph.invoke(initial)
    except Exception as e:  # noqa: BLE001
        session_log.event("turn_unhandled_error", trace_id=trace_id, error=str(e))
        session_log.close()
        raise HTTPException(500, f"agent error (trace_id={trace_id}): {e}") from e
    session_log.event("turn_end", trace_id=trace_id)
    session_log.close()
    return ChatResponse(
        trace_id=trace_id,
        final_message=final.get("final_message") or "(no output)",
        report=final.get("report"),
        sql=final.get("sql"),
        intent=final.get("intent"),
        saveable=bool(final.get("report")),
    )


# --- streaming -------------------------------------------------------------


class _StreamingSessionLog(SessionLog):
    """SessionLog that also publishes events to an in-memory queue.

    Inherits the file-based JSONL behavior so persistence is unchanged.
    """

    def __init__(self, q: "queue.Queue[Dict[str, Any]]", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._q = q

    def event(self, event: str, **fields: Any) -> None:  # type: ignore[override]
        super().event(event, **fields)
        # Only forward node-progress and key milestones to the client.
        if event in {
            "node_start",
            "node_end",
            "node_error",
            "sql_generated",
            "validate_dryrun_fail",
            "validate_static_fail",
            "validate_ok",
            "execute_ok",
            "execute_fail",
            "mask_done",
            "report_done",
            "report_pii_leak_caught",
        }:
            self._q.put({"type": "node", "event": event, **fields})


def _run_graph_in_thread(
    graph_resources: Dict[str, Any],
    initial: Dict[str, Any],
    q: "queue.Queue[Dict[str, Any]]",
) -> None:
    from src.api.deps import get_resources

    res = get_resources()
    try:
        final = res.graph.invoke(initial)
        q.put({"type": "done", "final": final})
    except Exception as e:  # noqa: BLE001
        logger.exception("graph error")
        q.put({"type": "error", "error": str(e)})


async def _sse_generator(req: ChatRequest, identity: Identity) -> AsyncIterator[Dict[str, Any]]:
    q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    trace_id = uuid.uuid4().hex[:10]
    session_log = _StreamingSessionLog(q=q)
    session_log.event(
        "turn_start",
        trace_id=trace_id,
        user=identity.user_id,
        role=identity.role,
        user_msg=req.question,
        source="api-sse",
    )

    initial: Dict[str, Any] = {
        "question": req.question,
        "user_id": identity.user_id,
        "trace_id": trace_id,
        "sql_attempts": 0,
        "resources": base_graph_resources(session_log),
    }

    try:
        yield {
            "event": "open",
            "data": json.dumps({"trace_id": trace_id}),
        }

        worker = threading.Thread(
            target=_run_graph_in_thread,
            args=(initial["resources"], initial, q),
            daemon=True,
        )
        worker.start()

        final: Optional[Dict[str, Any]] = None
        error: Optional[str] = None

        while True:
            try:
                item = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: q.get(timeout=120)
                )
            except queue.Empty:
                error = "agent timeout"
                break

            if item.get("type") == "node":
                payload = {k: v for k, v in item.items() if k != "type"}
                yield {"event": "node", "data": json.dumps(payload, default=str)}
                continue

            if item.get("type") == "error":
                error = item.get("error", "unknown error")
                break

            if item.get("type") == "done":
                final = item["final"]
                break

        if error:
            yield {"event": "error", "data": json.dumps({"error": error, "trace_id": trace_id})}
        elif final is not None:
            # Stream the report back as a single delta (LangGraph's invoke is
            # synchronous and the model already returned the full text).
            report = final.get("report") or final.get("final_message") or ""
            chunk_size = 40
            for i in range(0, len(report), chunk_size):
                yield {"event": "delta", "data": json.dumps({"text": report[i : i + chunk_size]})}
                await asyncio.sleep(0.01)  # tiny pacing for visible streaming

            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "trace_id": trace_id,
                        "final_message": final.get("final_message"),
                        "report": final.get("report"),
                        "sql": final.get("sql"),
                        "intent": final.get("intent"),
                        "saveable": bool(final.get("report")),
                    },
                    default=str,
                ),
            }
    finally:
        # Always close the session log, even if the client disconnects.
        try:
            session_log.event("turn_end", trace_id=trace_id)
        except Exception:
            pass
        session_log.close()


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest, identity: Identity = Depends(get_identity)
) -> EventSourceResponse:
    return EventSourceResponse(_sse_generator(req, identity))
