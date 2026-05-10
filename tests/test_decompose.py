"""Multi-question (compound) query support.

Tests the decompose / run_compound / synthesize chain end-to-end with a
prompt-routing FakeLLM. Covers:
  - single-question pass-through (no behavior change vs. baseline)
  - genuine compound: 2 sub-questions → 2 SQL flows → synthesized report
  - related-aggregates correctly NOT decomposed
  - sub-failure: one sub fails validation → synthesize still runs and
    reports the partial answer
  - decompose error / malformed JSON → graceful single-question fallback
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import pytest
from langchain_core.messages import AIMessage

from src.graph import nodes
from src.graph.builder import build_graph
from src.obs.log import SessionLog
from src.tools.golden_bucket import RetrievalResult, Trio


# --- fakes -----------------------------------------------------------------


class PromptAwareLLM:
    """Routes responses by system-prompt content. Each list is consumed
    in order as calls of that kind arrive."""

    def __init__(
        self,
        contextualize: List[str] | None = None,
        router: List[str] | None = None,
        decompose: List[str] | None = None,
        sql: List[str] | None = None,
        report: List[str] | None = None,
        synthesize: List[str] | None = None,
    ):
        self.contextualize = list(contextualize or [])
        self.router = list(router or [])
        self.decompose = list(decompose or [])
        self.sql = list(sql or [])
        self.report = list(report or [])
        self.synthesize = list(synthesize or [])
        self.calls: List[Dict[str, Any]] = []

    def invoke(self, messages):
        sys_text = messages[0].content if messages else ""
        kind = self._classify(sys_text)
        self.calls.append({"kind": kind})
        bucket = getattr(self, kind, None)
        if bucket is None:
            return AIMessage(content="(unknown prompt kind)")
        if not bucket:
            raise AssertionError(f"ran out of canned {kind} responses")
        return AIMessage(content=bucket.pop(0))

    @staticmethod
    def _classify(sys_text: str) -> str:
        if "rewrite a user's follow-up question" in sys_text:
            return "contextualize"
        if "classify a user's message into one intent" in sys_text:
            return "router"
        if "decompose a user's analytical question" in sys_text:
            return "decompose"
        if "SQL generator for Google BigQuery" in sys_text:
            return "sql"
        if "retail data analyst writing a report" in sys_text:
            return "report"
        if "combine N analyst reports" in sys_text:
            return "synthesize"
        return "unknown"


class FakeBQ:
    def __init__(self, frames: List[pd.DataFrame]):
        self._frames = list(frames)
        self.dry_calls = 0
        self.exec_calls = 0

    def dry_run_query(self, _sql):
        self.dry_calls += 1
        return True, None, 0

    def execute_query(self, _sql):
        self.exec_calls += 1
        if not self._frames:
            return pd.DataFrame()
        return self._frames.pop(0)


class FakeBucket:
    def retrieve(self, _q, k=3):
        return [Trio(id="t1", question="ex", sql="SELECT 1", report="", tags=[])]

    def retrieve_with_meta(self, _q, k=3, mode=None):
        return RetrievalResult(
            trios=self.retrieve(_q, k),
            mode=mode or "hybrid",
            cosine_top_idxs=[0],
            bm25_top_idxs=[0],
            final_idxs=[0],
        )


def _resources(llm, bq, session):
    return {
        "llm": llm,
        "bq": bq,
        "golden_bucket": FakeBucket(),
        "schema_summary": "(test schema)",
        "session": session,
    }


def _run(question, llm, bq, session, *, history=None):
    graph = build_graph()
    state = {
        "question": question,
        "user_id": "alice",
        "trace_id": "trace-test",
        "history": history or [],
        "now_utc": "2026-05-10T14:32:00Z",
        "sql_attempts": 0,
        "resources": _resources(llm, bq, session),
    }
    return graph.invoke(state)


# --- decompose unit tests --------------------------------------------------


def test_decompose_single_question_passes_through(tmp_path):
    llm = PromptAwareLLM(decompose=[
        '{"is_compound":false,"sub_questions":[],"reasoning":"single question"}'
    ])
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")
    state = {
        "question": "Top 10 customers by spend",
        "trace_id": "t",
        "resources": {"llm": llm, "session": session},
    }
    out = nodes.decompose_node(state)
    assert out == {"is_compound": False, "sub_questions": []}


def test_decompose_compound_returns_subs(tmp_path):
    llm = PromptAwareLLM(decompose=[
        '{"is_compound":true,'
        '"sub_questions":["Top 10 products by revenue last quarter",'
        '"Top 5 customers by spend last quarter"],'
        '"reasoning":"two independent analyses"}'
    ])
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")
    state = {
        "question": "top 10 products by revenue and top 5 customers by spend last quarter",
        "trace_id": "t",
        "resources": {"llm": llm, "session": session},
    }
    out = nodes.decompose_node(state)
    assert out["is_compound"] is True
    assert len(out["sub_questions"]) == 2
    assert "products" in out["sub_questions"][0].lower()
    assert "customers" in out["sub_questions"][1].lower()


def test_decompose_related_aggregates_not_split(tmp_path):
    """`top 10 customers and their average spend` is one analysis, not two.
    The model must NOT decompose it."""
    llm = PromptAwareLLM(decompose=[
        '{"is_compound":false,"sub_questions":[],'
        '"reasoning":"two aggregates over the same group"}'
    ])
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")
    state = {
        "question": "top 10 customers and their average spend",
        "trace_id": "t",
        "resources": {"llm": llm, "session": session},
    }
    out = nodes.decompose_node(state)
    assert out["is_compound"] is False


def test_decompose_clamps_too_many_subs(tmp_path):
    """If the model returns >MAX sub-questions, fall back to single."""
    over_limit = nodes._MAX_SUB_QUESTIONS + 1
    too_many = ", ".join([f'"q{i}"' for i in range(over_limit)])
    llm = PromptAwareLLM(decompose=[
        f'{{"is_compound":true,"sub_questions":[{too_many}],"reasoning":"too many"}}'
    ])
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")
    state = {"question": "x", "trace_id": "t", "resources": {"llm": llm, "session": session}}
    out = nodes.decompose_node(state)
    assert out["is_compound"] is False  # clamped


def test_decompose_malformed_json_falls_back(tmp_path):
    llm = PromptAwareLLM(decompose=["I'm not returning JSON, sorry"])
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")
    state = {"question": "x", "trace_id": "t", "resources": {"llm": llm, "session": session}}
    out = nodes.decompose_node(state)
    assert out["is_compound"] is False
    assert out["sub_questions"] == []


def test_decompose_llm_error_falls_back(tmp_path):
    class BoomLLM:
        def invoke(self, _msgs):
            raise RuntimeError("LLM down")

    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")
    state = {"question": "x", "trace_id": "t", "resources": {"llm": BoomLLM(), "session": session}}
    out = nodes.decompose_node(state)
    assert out["is_compound"] is False


# --- end-to-end through the graph -----------------------------------------


def test_compound_flow_runs_two_subs_and_synthesizes(tmp_path):
    """Top 10 products + top 5 customers → 2 sub-flows → synthesize."""
    df_products = pd.DataFrame({"name": ["P1", "P2"], "rev": [100, 90]})
    df_customers = pd.DataFrame({"id": [1, 2], "spend": [50, 40]})

    llm = PromptAwareLLM(
        router=[
            '{"intent":"analysis","confidence":0.95,"reason":"data"}',
        ],
        decompose=[
            '{"is_compound":true,'
            '"sub_questions":["top 10 products by revenue last quarter",'
            '"top 5 customers by spend last quarter"],'
            '"reasoning":"two analyses"}'
        ],
        sql=[
            "SELECT name, sale_price FROM `bigquery-public-data.thelook_ecommerce.products`",
            "SELECT id, spend FROM `bigquery-public-data.thelook_ecommerce.users`",
        ],
        report=[
            "Top products: P1 ($100), P2 ($90).",
            "Top customers: 1 ($50), 2 ($40).",
        ],
        synthesize=[
            "## Top products\nP1 ($100), P2 ($90).\n\n## Top customers\n1 ($50), 2 ($40)."
        ],
    )
    bq = FakeBQ(frames=[df_products, df_customers])
    session = SessionLog(session_id="cmp", path=tmp_path / "cmp.jsonl")

    final = _run(
        "top 10 products by revenue and top 5 customers by spend last quarter",
        llm, bq, session,
    )

    assert final.get("is_compound") is True
    sub_results = final.get("sub_results") or []
    assert len(sub_results) == 2
    assert sub_results[0]["error"] is None
    assert sub_results[1]["error"] is None
    assert sub_results[0]["row_count"] == 2
    assert sub_results[1]["row_count"] == 2
    # Each sub got its own derived trace_id.
    assert sub_results[0]["sub_trace_id"] == "trace-test.s0"
    assert sub_results[1]["sub_trace_id"] == "trace-test.s1"
    # Synthesized report is the user-facing message.
    assert "Top products" in final["final_message"]
    assert "Top customers" in final["final_message"]
    # 2 BQ executes (one per sub).
    assert bq.exec_calls == 2


def test_compound_flow_handles_partial_failure(tmp_path):
    """If one sub fails (validate gives up), synthesize still runs and
    reports the partial result."""
    df_ok = pd.DataFrame({"name": ["P1"], "rev": [100]})

    # Sub 0 succeeds; sub 1 fails validation across both retry attempts.
    # SQL_RETRY_LIMIT defaults to 2, so we need 2 SQL responses for sub 1
    # (both will be rejected).
    llm = PromptAwareLLM(
        router=['{"intent":"analysis","confidence":0.9,"reason":"data"}'],
        decompose=[
            '{"is_compound":true,'
            '"sub_questions":["top products","top customers"],'
            '"reasoning":"two analyses"}'
        ],
        sql=[
            "SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.orders`",  # sub 0
            "SELECT bogus FROM `bigquery-public-data.thelook_ecommerce.orders`",  # sub 1 try 1
            "SELECT bogus2 FROM `bigquery-public-data.thelook_ecommerce.orders`",  # sub 1 try 2
        ],
        report=[
            "Top products: P1 ($100).",  # only sub 0 reaches report
        ],
        synthesize=[
            "## Top products\nP1 ($100).\n\n## Top customers\n_(error: validate failed)_"
        ],
    )

    # FakeBQ: sub 0 dry_run ok + execute returns df_ok; sub 1 dry_run fails twice.
    class FakeBQRouting:
        def __init__(self):
            self.dry_calls = 0
            self.exec_calls = 0
            self._dry_results = [(True, None), (False, "bad column"), (False, "bad column")]
            self._exec_frames = [df_ok]

        def dry_run_query(self, _sql):
            ok, err = self._dry_results.pop(0) if self._dry_results else (True, None)
            self.dry_calls += 1
            return ok, err, 0

        def execute_query(self, _sql):
            self.exec_calls += 1
            return self._exec_frames.pop(0) if self._exec_frames else pd.DataFrame()

    bq = FakeBQRouting()
    session = SessionLog(session_id="partial", path=tmp_path / "partial.jsonl")

    final = _run("top products and top customers", llm, bq, session)

    sub_results = final.get("sub_results") or []
    assert len(sub_results) == 2
    assert sub_results[0]["error"] is None
    assert sub_results[1]["error"] is not None
    assert "validate" in sub_results[1]["error"]
    # Synthesize still produced an output.
    assert "Top products" in final["final_message"]
    # Only sub 0 actually executed against BQ.
    assert bq.exec_calls == 1


def test_single_question_path_unchanged(tmp_path):
    """Decompose's pass-through must not change the existing single-question
    behavior (byte-for-byte same number of nodes, same output)."""
    df = pd.DataFrame({"id": [1]})
    llm = PromptAwareLLM(
        router=['{"intent":"analysis","confidence":0.95,"reason":"data"}'],
        decompose=['{"is_compound":false,"sub_questions":[],"reasoning":"single"}'],
        sql=["SELECT id FROM `bigquery-public-data.thelook_ecommerce.orders` LIMIT 1"],
        report=["One row: id=1."],
    )
    bq = FakeBQ(frames=[df])
    session = SessionLog(session_id="single", path=tmp_path / "single.jsonl")

    final = _run("Show me one order", llm, bq, session)

    assert final.get("is_compound") is False
    assert final.get("sub_results") in (None, [])
    assert "One row" in final["final_message"]
    # No synthesize call was made — sub-results path skipped.
    kinds = [c["kind"] for c in llm.calls]
    assert "synthesize" not in kinds
