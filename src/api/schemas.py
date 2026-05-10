"""Pydantic v2 request/response schemas for the API."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# --- chat ------------------------------------------------------------------


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    thread_id: Optional[str] = Field(
        default=None,
        description=(
            "Conversation thread to continue. Omit on the first turn; the "
            "server returns a thread_id the client must send back on subsequent turns."
        ),
    )


class SubResult(BaseModel):
    sub_question: str
    sub_trace_id: str
    sql: Optional[str] = None
    report: Optional[str] = None
    row_count: int = 0
    error: Optional[str] = None


class ChatResponse(BaseModel):
    trace_id: str
    thread_id: str
    final_message: str
    report: Optional[str] = None
    sql: Optional[str] = None
    intent: Optional[str] = None
    saveable: bool = False
    # Multi-turn context fields. raw_question is what the user typed;
    # rewritten_question is the contextualize output. history_used is
    # true only when the rewriter actually changed the question.
    raw_question: Optional[str] = None
    rewritten_question: Optional[str] = None
    history_used: bool = False
    needs_clarification: bool = False
    turn_count: int = 0
    # Set on a refusal that the user can override via /api/chat/recover.
    recovery_token: Optional[str] = None
    refused_intent: Optional[str] = None
    # Compound-query support. Populated only when the decomposer split
    # the input into multiple sub-questions; otherwise null/empty.
    is_compound: bool = False
    sub_questions: Optional[List[str]] = None
    sub_results: Optional[List[SubResult]] = None


class RecoverRequest(BaseModel):
    """Override a router refusal. The client passes the refused turn's
    `recovery_token` (== trace_id) plus the original question; the server
    logs the correction and re-runs the question with intent forced to
    `analysis`."""
    recovery_token: str
    raw_question: str = Field(..., min_length=1, max_length=4000)
    thread_id: Optional[str] = None


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


# --- threads ---------------------------------------------------------------


class ThreadOut(BaseModel):
    thread_id: str
    title: Optional[str] = None
    created_at: float
    updated_at: float
    last_message_at: Optional[float] = None
    archived: bool = False


class ThreadsListResponse(BaseModel):
    threads: List[ThreadOut]


class CreateThreadRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)


class UpdateThreadRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    archived: Optional[bool] = None


class ThreadMessage(BaseModel):
    role: str               # "user" | "assistant"
    content: str
    created_at: float
    trace_id: Optional[str] = None
    turn_idx: int


class ThreadMessagesResponse(BaseModel):
    thread_id: str
    title: Optional[str] = None
    messages: List[ThreadMessage]


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
