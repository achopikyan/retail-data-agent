"""LangGraph state schema."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict  # noqa: F401

import pandas as pd

from src.tools.golden_bucket import Trio


Intent = Literal[
    "analysis",
    "persona_change",
    "reports_crud",
    "smalltalk",
    "out_of_scope",
    "injection",
]


class AgentState(TypedDict, total=False):
    # Input
    question: str
    user_id: str
    trace_id: str

    # Conversation context (loaded once at turn start; per-turn nodes
    # never mutate it, which keeps single-turn determinism intact).
    thread_id: Optional[str]
    history: List[Dict[str, Any]]      # [{"role", "content", "created_at"}]
    now_utc: Optional[str]             # ISO8601 captured at turn start
    raw_question: Optional[str]        # the user's literal phrasing
    rewritten_question: Optional[str]  # post-contextualize, used downstream
    history_used: bool                 # whether the rewriter actually consulted history
    needs_clarification: bool          # contextualize aborted with a clarifying Q
    clarifying_question: Optional[str]

    # Routing
    intent: Optional[Intent]
    refusal_reason: Optional[str]
    # Set by /api/chat/recover to skip the router classifier and force
    # the analysis path. Used after a user overrides a refusal.
    bypass_router: bool

    # Compound (multi-question) support. `is_compound=True` triggers
    # the run_compound branch which runs the analytical flow once per
    # sub_question and synthesizes a multi-section report.
    is_compound: bool
    sub_questions: List[str]
    sub_results: List[Dict[str, Any]]
    # [{sub_question, sub_trace_id, sql, report, row_count, error}, ...]

    # Retrieval
    retrieved_trios: List[Trio]

    # SQL pipeline
    sql: Optional[str]
    sql_attempts: int
    sql_error: Optional[str]
    last_failure_kind: Optional[str]  # "validate" | "execute" | "empty"

    # Execution
    bq_result_df: Optional[pd.DataFrame]
    masked_df: Optional[pd.DataFrame]
    pii_masked_columns: List[str]
    pii_cell_hits: int

    # Output
    report: Optional[str]
    final_message: Optional[str]
    error: Optional[str]
    # Set by refuse_node so the API can return a token the client uses
    # to override the block via POST /api/chat/recover.
    recovery_token: Optional[str]

    # Resources (passed in at run time)
    resources: Dict[str, Any]
