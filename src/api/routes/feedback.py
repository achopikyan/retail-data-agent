"""Up/down feedback on the most recent turn."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.schemas import FeedbackRequest, FeedbackStats
from src.tools import feedback_store

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.post("", status_code=204)
def submit_feedback(req: FeedbackRequest) -> None:
    try:
        ok = feedback_store.set_feedback(req.trace_id, req.vote)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not ok:
        raise HTTPException(404, "no pending_trios row for that trace_id")


@router.get("/stats", response_model=FeedbackStats)
def stats() -> FeedbackStats:
    s = feedback_store.stats()
    return FeedbackStats(**s)
