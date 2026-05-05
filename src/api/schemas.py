"""Pydantic v2 request/response schemas for the API."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# --- chat ------------------------------------------------------------------


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    trace_id: str
    final_message: str
    report: Optional[str] = None
    sql: Optional[str] = None
    intent: Optional[str] = None
    saveable: bool = False


# --- reports ---------------------------------------------------------------


class ReportOut(BaseModel):
    id: int
    owner_id: str
    title: str
    body: str
    created_at: float
    updated_at: float


class SaveReportRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1)


class DeleteMatchingRequest(BaseModel):
    substring: str = Field(..., min_length=1)
    expected_count: Optional[int] = Field(
        default=None,
        description=(
            "Required for cross-user (gdpr_officer) deletes — must equal the "
            "number of reports the substring matches."
        ),
    )
    reason: str = ""


class DeleteResponse(BaseModel):
    deleted: int
    target_ids: List[int]


# --- audit -----------------------------------------------------------------


class AuditEntry(BaseModel):
    id: int
    ts: float
    actor_id: str
    action: str
    target_ids: str
    reason: Optional[str]
    trace_id: Optional[str]


# --- feedback --------------------------------------------------------------


class FeedbackRequest(BaseModel):
    trace_id: str
    vote: Literal["up", "down"]


class FeedbackStats(BaseModel):
    total: int
    up: int
    down: int
    promoted: int


# --- prefs -----------------------------------------------------------------


class PrefsOut(BaseModel):
    user_id: str
    prefs: dict[str, str]


class SetPrefRequest(BaseModel):
    key: str
    value: str


# --- personas --------------------------------------------------------------


class PersonaOut(BaseModel):
    name: str
    description: str
    instructions: str


class PersonasResponse(BaseModel):
    active: str
    personas: List[PersonaOut]


# --- sessions --------------------------------------------------------------


class SessionEvent(BaseModel):
    ts: float
    event: str
    trace_id: Optional[str] = None
    node: Optional[str] = None
    latency_ms: Optional[float] = None
    extras: dict = Field(default_factory=dict)


class SessionResponse(BaseModel):
    session_id: str
    events: List[SessionEvent]
