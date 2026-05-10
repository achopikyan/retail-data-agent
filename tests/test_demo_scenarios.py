"""End-to-end demos for the two reviewer scenarios.

These exercise the FULL graph (contextualize → router → retrieve → sql_gen →
validate → execute → mask → report) with fake BQ + LLM, asserting on the
behaviors that distinguish the new history support:

  Scenario 1 — recall:
    user> Show me Q3 2025 revenue by region
    user> What was that revenue number again?
        → contextualize must rewrite "that revenue number" against turn 1
        → SQL writer must see the rewritten question
        → history_used=True, fresh SQL is run (re-grounded in current data)

  Scenario 2 — backtrack:
    user> Show me Q3 2025 revenue by region
    user> Top 10 products by units sold        ← unrelated
    user> Going back to that earlier analysis, break it down by category
        → contextualize must reference TURN 1, not turn 2 (most recent)
        → rewrite must mention the Q3 revenue topic, not the products one
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import pytest
from langchain_core.messages import AIMessage

from src import settings
from src.graph.builder import build_graph
from src.obs.log import SessionLog
from src.tools import threads_store
from src.tools.golden_bucket import Trio


# --- fakes -----------------------------------------------------------------


class PromptAwareLLM:
    """FakeLLM that picks a response based on which system prompt arrives.

    The graph calls the LLM from three nodes (contextualize, sql_gen,
    report), each with a distinctive system prompt. Routing on prompt
    content lets the test stay readable even as turn count grows.
    """

    def __init__(self, contextualize_jsons: List[str], sqls: List[str], reports: List[str]):
        self.cx = list(contextualize_jsons)
        self.sqls = list(sqls)
        self.reports = list(reports)
        self.calls: List[Dict[str, Any]] = []

    def invoke(self, messages):
        sys_text = messages[0].content if messages else ""
        user_text = messages[1].content if len(messages) > 1 else ""
        kind = self._classify(sys_text)
        self.calls.append({"kind": kind, "user_text": user_text})

        if kind == "contextualize":
            assert self.cx, "ran out of contextualize responses"
            return AIMessage(content=self.cx.pop(0))
        if kind == "sql_gen":
            assert self.sqls, "ran out of sql responses"
            return AIMessage(content=self.sqls.pop(0))
        if kind == "report":
            assert self.reports, "ran out of report responses"
            return AIMessage(content=self.reports.pop(0))
        # Auto-titler isn't called from graph.invoke — only from the
        # chat route — so this path shouldn't fire in these tests.
        return AIMessage(content="(unexpected llm call)")

    @staticmethod
    def _classify(sys_text: str) -> str:
        if "rewrite a user's follow-up question" in sys_text:
            return "contextualize"
        if "SQL generator for Google BigQuery" in sys_text:
            return "sql_gen"
        if "retail data analyst writing a report" in sys_text:
            return "report"
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
        return [
            Trio(
                id="t1",
                question="example",
                sql="SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.orders`",
                report="example report",
                tags=[],
            )
        ]


# --- helpers ---------------------------------------------------------------


def _resources(llm, bq, session):
    return {
        "llm": llm,
        "bq": bq,
        "golden_bucket": FakeBucket(),
        "schema_summary": "(test schema)",
        "session": session,
    }


def _run_turn(graph, *, question, thread_id, history, now_utc, resources, user_id="alice"):
    state = {
        "question": question,
        "user_id": user_id,
        "trace_id": f"trace-{len(history)}",
        "thread_id": thread_id,
        "history": history,
        "now_utc": now_utc,
        "sql_attempts": 0,
        "resources": resources,
    }
    return graph.invoke(state)


# --- scenario 1: recall ----------------------------------------------------


def test_scenario_1_recall(tmp_path):
    """`What was that revenue number again?` resolves to the prior Q3 query."""
    session = SessionLog(session_id="demo-1", path=tmp_path / "demo-1.jsonl")
    graph = build_graph()

    # Turn-1 SQL + report
    sql_1 = (
        "SELECT region, ROUND(SUM(sale_price),2) AS revenue "
        "FROM `bigquery-public-data.thelook_ecommerce.order_items` oi "
        "JOIN `bigquery-public-data.thelook_ecommerce.users` u ON u.id = oi.user_id "
        "WHERE oi.status NOT IN ('Cancelled','Returned') "
        "  AND DATE(oi.created_at) BETWEEN '2025-07-01' AND '2025-09-30' "
        "GROUP BY region ORDER BY revenue DESC"
    )
    report_1 = (
        "Q3 2025 revenue by region:\n"
        "- Northeast: $12.4M\n- Midwest: $9.1M\n- South: $8.3M\n- West: $7.7M"
    )
    df_1 = pd.DataFrame({
        "region": ["Northeast", "Midwest", "South", "West"],
        "revenue": [12_400_000, 9_100_000, 8_300_000, 7_700_000],
    })

    # Turn-2 contextualize: rewrite to a self-contained, dated question
    cx_2 = (
        '{"rewritten":"What was the Q3 2025 revenue figure for Northeast '
        '(July-Sep 2025), excluding cancellations/returns?",'
        '"confidence":0.92,"ambiguous":false,"referenced_turn_idxs":[0,1],'
        '"clarifying_question":null}'
    )
    sql_2 = (
        "SELECT ROUND(SUM(sale_price),2) AS revenue "
        "FROM `bigquery-public-data.thelook_ecommerce.order_items` oi "
        "JOIN `bigquery-public-data.thelook_ecommerce.users` u ON u.id = oi.user_id "
        "WHERE oi.status NOT IN ('Cancelled','Returned') "
        "  AND u.region = 'Northeast' "
        "  AND DATE(oi.created_at) BETWEEN '2025-07-01' AND '2025-09-30'"
    )
    report_2 = "Q3 2025 Northeast revenue (Jul-Sep, excl. returns): $12.4M."
    df_2 = pd.DataFrame({"revenue": [12_400_000]})

    llm = PromptAwareLLM(
        contextualize_jsons=[cx_2],
        sqls=[sql_1, sql_2],
        reports=[report_1, report_2],
    )
    bq = FakeBQ(frames=[df_1, df_2])
    resources = _resources(llm, bq, session)

    # Real thread_id — the turn-2 history is loaded from the same store
    # that turn-1 wrote to, mirroring the production path exactly.
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")

    # Turn 1 — empty history → contextualize short-circuits.
    final_1 = _run_turn(
        graph,
        question="Show me Q3 2025 revenue by region",
        thread_id=tid,
        history=[],
        now_utc="2026-05-10T14:00:00Z",
        resources=resources,
    )
    assert final_1.get("report"), "turn-1 must produce a real analytical report"
    assert final_1["history_used"] is False
    threads_store.append_turn(
        tid, "alice",
        user_question=final_1.get("raw_question") or "Show me Q3 2025 revenue by region",
        assistant_response=final_1["report"],
        trace_id="trace-0",
    )

    # Turn 2 — history present → contextualize MUST be called and rewrite.
    history_2 = threads_store.get_recent_messages(tid, settings.MAX_HISTORY_MESSAGES)
    assert len(history_2) == 2, "turn-1 should have written user+assistant rows"

    final_2 = _run_turn(
        graph,
        question="What was that revenue number again?",
        thread_id=tid,
        history=history_2,
        now_utc="2026-05-10T14:32:00Z",
        resources=resources,
    )

    # The contextualize node must have run.
    cx_calls = [c for c in llm.calls if c["kind"] == "contextualize"]
    assert len(cx_calls) == 1, "contextualize must be called when history is non-empty"

    # raw_question is preserved for audit; rewritten_question is what the
    # graph actually used downstream.
    assert final_2["raw_question"] == "What was that revenue number again?"
    assert "Northeast" in final_2["rewritten_question"]
    assert final_2["history_used"] is True
    # SQL was actually run — we re-grounded in fresh data, not just recalled.
    assert bq.exec_calls == 2
    assert "Northeast" in (final_2.get("sql") or "")
    # The contextualize prompt saw the prior turn's content (so it could
    # actually resolve the referent).
    assert "Northeast" in cx_calls[0]["user_text"]
    # And the prompt told the model the current time (for date resolution).
    assert "2026-05-10" in cx_calls[0]["user_text"]


# --- scenario 2: backtrack -------------------------------------------------


def test_scenario_2_backtrack(tmp_path):
    """`Going back to that earlier analysis...` references turn-1, not turn-2."""
    session = SessionLog(session_id="demo-2", path=tmp_path / "demo-2.jsonl")
    graph = build_graph()

    # Turn-1: revenue by region
    sql_1 = "SELECT region, SUM(sale_price) FROM `bigquery-public-data.thelook_ecommerce.order_items` GROUP BY region"
    report_1 = "Q3 2025 revenue by region: Northeast $12.4M, Midwest $9.1M ..."
    df_1 = pd.DataFrame({"region": ["Northeast"], "revenue": [12_400_000]})

    # Turn-2: top products (unrelated topic). Self-contained ⇒ contextualize
    # is called (history present) but should pass through unchanged.
    cx_2 = (
        '{"rewritten":"Top 10 products by units sold","confidence":0.95,'
        '"ambiguous":false,"referenced_turn_idxs":[],"clarifying_question":null}'
    )
    sql_2 = "SELECT name, COUNT(*) FROM `bigquery-public-data.thelook_ecommerce.products` GROUP BY name LIMIT 10"
    report_2 = "Top 10 products by units sold: ..."
    df_2 = pd.DataFrame({"name": [f"P{i}" for i in range(10)], "units": list(range(10, 0, -1))})

    # Turn-3: backtrack to turn-1's analysis with a NEW dimension.
    # The rewrite must reference Q3 revenue (turn-1), NOT products (turn-2).
    cx_3 = (
        '{"rewritten":"Q3 2025 revenue broken down by product category, '
        'excluding cancellations/returns","confidence":0.88,"ambiguous":false,'
        '"referenced_turn_idxs":[0,1],"clarifying_question":null}'
    )
    sql_3 = (
        "SELECT p.category, ROUND(SUM(oi.sale_price),2) AS revenue "
        "FROM `bigquery-public-data.thelook_ecommerce.order_items` oi "
        "JOIN `bigquery-public-data.thelook_ecommerce.products` p ON p.id = oi.product_id "
        "WHERE oi.status NOT IN ('Cancelled','Returned') "
        "  AND DATE(oi.created_at) BETWEEN '2025-07-01' AND '2025-09-30' "
        "GROUP BY p.category ORDER BY revenue DESC"
    )
    report_3 = "Q3 2025 revenue by category: ..."
    df_3 = pd.DataFrame({"category": ["Outerwear"], "revenue": [3_200_000]})

    llm = PromptAwareLLM(
        contextualize_jsons=[cx_2, cx_3],
        sqls=[sql_1, sql_2, sql_3],
        reports=[report_1, report_2, report_3],
    )
    bq = FakeBQ(frames=[df_1, df_2, df_3])
    resources = _resources(llm, bq, session)

    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")

    # Turn 1
    final_1 = _run_turn(
        graph,
        question="Show me Q3 2025 revenue by region",
        thread_id=tid, history=[],
        now_utc="2026-05-08T09:15:00Z", resources=resources,
    )
    threads_store.append_turn(
        tid, "alice", "Show me Q3 2025 revenue by region", final_1["report"], "trace-0"
    )

    # Turn 2 — different topic. Contextualize is called but is a no-op rewrite.
    history_2 = threads_store.get_recent_messages(tid)
    final_2 = _run_turn(
        graph,
        question="Top 10 products by units sold",
        thread_id=tid, history=history_2,
        now_utc="2026-05-08T09:20:00Z", resources=resources,
    )
    assert final_2["history_used"] is False, "self-contained Q ⇒ no rewrite"
    threads_store.append_turn(
        tid, "alice", "Top 10 products by units sold", final_2["report"], "trace-1"
    )

    # Turn 3 — backtrack
    history_3 = threads_store.get_recent_messages(tid)
    assert len(history_3) == 4, "two prior turns ⇒ four messages"

    final_3 = _run_turn(
        graph,
        question="Going back to that earlier analysis, break it down by category",
        thread_id=tid, history=history_3,
        now_utc="2026-05-08T09:25:00Z", resources=resources,
    )

    # Critical assertion: the rewrite picked turn-1 (revenue) over turn-2
    # (products). If the model anchored on the most-recent turn, "category"
    # would mean product category counts, not Q3 revenue by category.
    rewritten = final_3["rewritten_question"]
    assert "revenue" in rewritten.lower(), f"backtrack must reference revenue: {rewritten!r}"
    assert "Q3 2025" in rewritten, f"backtrack must reference Q3 timeframe: {rewritten!r}"
    assert final_3["history_used"] is True
    # Fresh SQL was run for the backtracked analysis.
    assert bq.exec_calls == 3
    assert "category" in (final_3.get("sql") or "").lower()
    # And the contextualize prompt saw both prior turns (so it could choose).
    cx_calls = [c for c in llm.calls if c["kind"] == "contextualize"]
    last_cx_prompt = cx_calls[-1]["user_text"]
    assert "revenue" in last_cx_prompt.lower()
    assert "products" in last_cx_prompt.lower()


# --- bonus: clarify path ---------------------------------------------------


def test_scenario_clarify_when_ambiguous(tmp_path):
    """If the rewriter can't pick a referent, the graph routes to clarify
    and never runs SQL — the silent-miscontext failure mode is prevented.
    """
    session = SessionLog(session_id="demo-3", path=tmp_path / "demo-3.jsonl")
    graph = build_graph()

    # Two prior analyses both have "a number" in scope; "that number" is ambiguous.
    sql_1 = "SELECT 1 FROM `bigquery-public-data.thelook_ecommerce.orders`"
    sql_2 = "SELECT 2 FROM `bigquery-public-data.thelook_ecommerce.orders`"

    cx_3 = (
        '{"rewritten":"that number","confidence":0.4,"ambiguous":true,'
        '"referenced_turn_idxs":[1,3],"clarifying_question":'
        '"Which prior figure — the Q3 revenue or the return rate?"}'
    )

    llm = PromptAwareLLM(
        contextualize_jsons=[
            # Turn-2 self-contained pass-through
            '{"rewritten":"Show me return rate","confidence":0.95,"ambiguous":false,'
            '"referenced_turn_idxs":[],"clarifying_question":null}',
            cx_3,
        ],
        sqls=[sql_1, sql_2],  # Only 2 SQLs — turn 3 should never reach sql_gen.
        reports=[
            "Q3 revenue total: $50M.",
            "Return rate: 12%.",
        ],
    )
    bq = FakeBQ(frames=[
        pd.DataFrame({"x": [50_000_000]}),
        pd.DataFrame({"r": [0.12]}),
    ])
    resources = _resources(llm, bq, session)

    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")

    final_1 = _run_turn(graph, question="What was Q3 revenue?",
                        thread_id=tid, history=[],
                        now_utc="2026-05-10T10:00:00Z", resources=resources)
    threads_store.append_turn(tid, "alice", "What was Q3 revenue?", final_1["report"], "t0")

    history_2 = threads_store.get_recent_messages(tid)
    final_2 = _run_turn(graph, question="Show me return rate",
                        thread_id=tid, history=history_2,
                        now_utc="2026-05-10T10:05:00Z", resources=resources)
    threads_store.append_turn(tid, "alice", "Show me return rate", final_2["report"], "t1")

    history_3 = threads_store.get_recent_messages(tid)
    final_3 = _run_turn(graph, question="that number",
                        thread_id=tid, history=history_3,
                        now_utc="2026-05-10T10:10:00Z", resources=resources)

    # Clarify path was taken — final_message is the clarifying question.
    assert final_3["needs_clarification"] is True
    assert "Q3 revenue" in final_3["final_message"]
    assert "return rate" in final_3["final_message"]
    # Critically: NO SQL was generated for turn 3. The silent-wrong-answer
    # failure mode is prevented.
    assert bq.exec_calls == 2, "clarify must short-circuit before sql_gen"
    # And nothing analytical was produced — the route layer would skip
    # the transcript append.
    assert final_3.get("report") is None
