"""LangGraph state schema."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

import pandas as pd

from src.tools.golden_bucket import Trio


Intent = Literal[
    "analysis", "reports_crud", "smalltalk", "out_of_scope", "injection"
]


class AgentState(TypedDict, total=False):
    # Input
    question: str
    user_id: str
    trace_id: str

    # Routing
    intent: Optional[Intent]
    refusal_reason: Optional[str]

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

    # Resources (passed in at run time)
    resources: Dict[str, Any]
