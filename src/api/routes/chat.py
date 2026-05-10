"""Chat routes — POST /api/chat (non-streaming) and POST /api/chat/stream (SSE).

The SSE handler runs the LangGraph in a worker thread and forwards
events from a queue to the SSE response. A custom SessionLog subclass
pushes node-level events onto the same queue, so the client sees node
progress in real time.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import queue
import threading
import uuid
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from src import settings
from src.api.deps import base_graph_resources, get_resources
from src.api.identity import Identity, get_identity
from src.api.schemas import ChatRequest, ChatResponse, RecoverRequest
from src.obs.log import SessionLog
from src.tools import auto_titler, feedback_store, threads_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


def _now_utc_iso() -> str:
    """Single source of truth for 'now' on a turn. UTC, second precision."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_thread(req_thread_id: Optional[str], user_id: str) -> str:
    """Resolve client-supplied thread_id, enforcing per-user scoping.

    - No thread_id → mint a new one and persist the row.
    - Existing thread_id with matching owner → reuse.
    - Existing thread_id with mismatched owner → 404 (don't leak existence by 403).
    - Unknown thread_id supplied → adopt it (allows client-generated UUIDs
      on the first turn of a thread the server hasn't seen yet).
    """
    if not req_thread_id:
        new_id = threads_store.new_thread_id()
        threads_store.ensure_thread(new_id, user_id)
        return new_id
    owner = threads_store.thread_owner(req_thread_id)
    if owner is not None and owner != user_id:
        raise HTTPException(404, "thread not found")
    threads_store.ensure_thread(req_thread_id, user_id)
    return req_thread_id


# --- non-streaming ---------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, identity: Identity = Depends(get_identity)) -> ChatResponse:
    res = get_resources()
    session_log = SessionLog()
    trace_id = uuid.uuid4().hex[:10]
    thread_id = _resolve_thread(req.thread_id, identity.user_id)
    history = threads_store.get_recent_messages(thread_id, settings.MAX_HISTORY_MESSAGES)
    now_utc = _now_utc_iso()
    session_log.event(
        "turn_start",
        trace_id=trace_id,
        user=identity.user_id,
        role=identity.role,
        thread_id=thread_id,
        history_len=len(history),
        now_utc=now_utc,
        user_msg=req.question,
        source="api",
    )
    initial: Dict[str, Any] = {
        "question": req.question,
        "user_id": identity.user_id,
        "trace_id": trace_id,
        "thread_id": thread_id,
        "history": history,
        "now_utc": now_utc,
        "sql_attempts": 0,
        "resources": base_graph_resources(session_log),
    }
    try:
        final = res.graph.invoke(initial)
    except Exception as e:  # noqa: BLE001
        session_log.event("turn_unhandled_error", trace_id=trace_id, error=str(e))
        session_log.close()
        raise HTTPException(500, f"agent error (trace_id={trace_id}): {e}") from e

    # Persist transcript turn ONLY when we produced a real analytical
    # report. Refusals, errors, and clarifications stay out of history
    # so they don't poison future rewrites.
    report = final.get("report")
    if report:
        try:
            threads_store.append_turn(
                thread_id=thread_id,
                user_id=identity.user_id,
                user_question=final.get("raw_question") or req.question,
                assistant_response=report,
                trace_id=trace_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to persist turn for thread %s: %s", thread_id, e)
            session_log.event("thread_persist_failed", trace_id=trace_id, error=str(e))
        # Best-effort auto-title on first successful turn.
        auto_titler.maybe_set_title(
            thread_id=thread_id,
            user_question=final.get("raw_question") or req.question,
            llm=res.llm,
        )

    session_log.event("turn_end", trace_id=trace_id)
    session_log.close()
    intent = final.get("intent")
    return ChatResponse(
        trace_id=trace_id,
        thread_id=thread_id,
        final_message=final.get("final_message") or "(no output)",
        report=report,
        sql=final.get("sql"),
        intent=intent,
        saveable=bool(report),
        raw_question=final.get("raw_question"),
        rewritten_question=final.get("rewritten_question"),
        history_used=bool(final.get("history_used")),
        needs_clarification=bool(final.get("needs_clarification")),
        turn_count=threads_store.turn_count(thread_id),
        recovery_token=final.get("recovery_token"),
        refused_intent=intent if intent in {"injection", "out_of_scope"} else None,
        is_compound=bool(final.get("is_compound")),
        sub_questions=final.get("sub_questions") or None,
        sub_results=final.get("sub_results") or None,
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
    thread_id = _resolve_thread(req.thread_id, identity.user_id)
    history = threads_store.get_recent_messages(thread_id, settings.MAX_HISTORY_MESSAGES)
    now_utc = _now_utc_iso()
    session_log = _StreamingSessionLog(q=q)
    session_log.event(
        "turn_start",
        trace_id=trace_id,
        user=identity.user_id,
        role=identity.role,
        thread_id=thread_id,
        history_len=len(history),
        now_utc=now_utc,
        user_msg=req.question,
        source="api-sse",
    )

    initial: Dict[str, Any] = {
        "question": req.question,
        "user_id": identity.user_id,
        "trace_id": trace_id,
        "thread_id": thread_id,
        "history": history,
        "now_utc": now_utc,
        "sql_attempts": 0,
        "resources": base_graph_resources(session_log),
    }

    try:
        # Send thread_id back on the open event so the client can lock
        # it in before any content arrives — handy if the user navigates
        # away mid-stream.
        yield {
            "event": "open",
            "data": json.dumps({"trace_id": trace_id, "thread_id": thread_id}),
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

            # Persist the turn before announcing done so the client's
            # turn_count in the done event reflects post-write state.
            real_report = final.get("report")
            if real_report:
                try:
                    threads_store.append_turn(
                        thread_id=thread_id,
                        user_id=identity.user_id,
                        user_question=final.get("raw_question") or req.question,
                        assistant_response=real_report,
                        trace_id=trace_id,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("Failed to persist turn for thread %s: %s", thread_id, e)
                    session_log.event("thread_persist_failed", trace_id=trace_id, error=str(e))
                # Best-effort auto-title on first successful turn.
                auto_titler.maybe_set_title(
                    thread_id=thread_id,
                    user_question=final.get("raw_question") or req.question,
                    llm=get_resources().llm,
                )

            intent = final.get("intent")
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "trace_id": trace_id,
                        "thread_id": thread_id,
                        "final_message": final.get("final_message"),
                        "report": real_report,
                        "sql": final.get("sql"),
                        "intent": intent,
                        "saveable": bool(real_report),
                        "raw_question": final.get("raw_question"),
                        "rewritten_question": final.get("rewritten_question"),
                        "history_used": bool(final.get("history_used")),
                        "needs_clarification": bool(final.get("needs_clarification")),
                        "turn_count": threads_store.turn_count(thread_id),
                        "recovery_token": final.get("recovery_token"),
                        "refused_intent": intent if intent in {"injection", "out_of_scope"} else None,
                        "is_compound": bool(final.get("is_compound")),
                        "sub_questions": final.get("sub_questions") or None,
                        "sub_results": final.get("sub_results") or None,
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


# --- recovery from a router false-positive --------------------------------


@router.post("/chat/recover", response_model=ChatResponse)
def chat_recover(
    req: RecoverRequest, identity: Identity = Depends(get_identity)
) -> ChatResponse:
    """Override a router refusal. Logs the correction (training data for
    classifier tuning) and re-runs the question with intent forced to
    `analysis` so the user gets unblocked.

    Per-user abuse mitigation: a user trips this far more than expected
    will show up in `feedback_store.router_correction_count(user_id)`,
    which feeds the production false-positive-rate metric. We don't
    rate-limit here in v1 — that goes in the Cloud Armor / token-bucket
    layer when we deploy.
    """
    res = get_resources()
    session_log = SessionLog()
    trace_id = uuid.uuid4().hex[:10]
    thread_id = _resolve_thread(req.thread_id, identity.user_id)
    history = threads_store.get_recent_messages(thread_id, settings.MAX_HISTORY_MESSAGES)
    now_utc = _now_utc_iso()

    # Log the correction first — even if the re-run fails, the labeled
    # case is preserved for classifier tuning.
    try:
        feedback_store.record_router_correction(
            trace_id=req.recovery_token,
            user_id=identity.user_id,
            raw_question=req.raw_question,
            refused_intent="unknown",  # we don't currently re-fetch the original; could be looked up from JSONL
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to record router correction: %s", e)

    session_log.event(
        "router_correction",
        trace_id=trace_id,
        original_trace_id=req.recovery_token,
        user=identity.user_id,
        raw_question=req.raw_question,
    )
    session_log.event(
        "turn_start",
        trace_id=trace_id,
        user=identity.user_id,
        role=identity.role,
        thread_id=thread_id,
        history_len=len(history),
        now_utc=now_utc,
        user_msg=req.raw_question,
        source="api-recover",
    )

    initial: Dict[str, Any] = {
        "question": req.raw_question,
        "user_id": identity.user_id,
        "trace_id": trace_id,
        "thread_id": thread_id,
        "history": history,
        "now_utc": now_utc,
        "sql_attempts": 0,
        # Skip the classifier so the user gets unblocked.
        "bypass_router": True,
        "resources": base_graph_resources(session_log),
    }

    try:
        final = res.graph.invoke(initial)
    except Exception as e:  # noqa: BLE001
        session_log.event("turn_unhandled_error", trace_id=trace_id, error=str(e))
        session_log.close()
        raise HTTPException(500, f"agent error (trace_id={trace_id}): {e}") from e

    report = final.get("report")
    if report:
        try:
            threads_store.append_turn(
                thread_id=thread_id,
                user_id=identity.user_id,
                user_question=req.raw_question,
                assistant_response=report,
                trace_id=trace_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to persist turn for thread %s: %s", thread_id, e)

    session_log.event("turn_end", trace_id=trace_id)
    session_log.close()

    intent = final.get("intent")
    return ChatResponse(
        trace_id=trace_id,
        thread_id=thread_id,
        final_message=final.get("final_message") or "(no output)",
        report=report,
        sql=final.get("sql"),
        intent=intent,
        saveable=bool(report),
        raw_question=req.raw_question,
        rewritten_question=final.get("rewritten_question"),
        history_used=bool(final.get("history_used")),
        needs_clarification=bool(final.get("needs_clarification")),
        turn_count=threads_store.turn_count(thread_id),
        recovery_token=final.get("recovery_token"),
        refused_intent=intent if intent in {"injection", "out_of_scope"} else None,
    )
