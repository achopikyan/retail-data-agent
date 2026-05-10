"""Contextualize node — anaphora resolution against prior turns.

We exercise the node directly rather than the full graph because the
rewrite logic is self-contained (no SQL, no BQ), and this lets us
assert on the structured state output without dragging every
downstream node into the test.
"""
from __future__ import annotations

import time
from typing import List

import pytest
from langchain_core.messages import AIMessage

from src.graph import nodes
from src.obs.log import SessionLog


# --- fakes -----------------------------------------------------------------


class FakeLLM:
    def __init__(self, responses: List[str]):
        self._responses = list(responses)
        self.calls: List[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self._responses.pop(0) if self._responses else "")


def _state(question: str, history, llm, session, now_utc="2026-05-10T14:32:00Z"):
    return {
        "question": question,
        "trace_id": "trace-test",
        "history": history,
        "now_utc": now_utc,
        "resources": {"llm": llm, "session": session},
    }


def _hist(role, content, ts=None):
    return {
        "role": role,
        "content": content,
        "created_at": ts if ts is not None else time.time() - 86400,
    }


# --- tests -----------------------------------------------------------------


def test_skips_when_no_history(tmp_path):
    """Empty history → no LLM call, raw passes through."""
    llm = FakeLLM([])
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")

    out = nodes.contextualize_node(_state("Top 10 customers by spend", [], llm, session))

    assert llm.calls == []
    assert out["raw_question"] == "Top 10 customers by spend"
    assert out["rewritten_question"] == "Top 10 customers by spend"
    assert out["history_used"] is False
    assert out["needs_clarification"] is False
    # No `question` override when we skipped — downstream sees the original.
    assert "question" not in out


def test_always_calls_llm_when_history_present(tmp_path):
    """No regex gate — the rewriter is called even on apparently-self-contained
    questions, and its prompt instructs pass-through. Verifies the design
    decision to drop heuristic gating.
    """
    llm = FakeLLM([
        '{"rewritten":"Show me the top 5 categories by revenue","confidence":0.95,'
        '"ambiguous":false,"referenced_turn_idxs":[],"clarifying_question":null}'
    ])
    history = [_hist("user", "earlier Q"), _hist("assistant", "earlier A")]
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")

    out = nodes.contextualize_node(
        _state("Show me the top 5 categories by revenue", history, llm, session)
    )

    # LLM was called even though there are no obvious deictics.
    assert len(llm.calls) == 1
    # Pass-through: rewritten == raw → history_used False.
    assert out["history_used"] is False
    assert out["rewritten_question"] == "Show me the top 5 categories by revenue"


def test_rewrites_when_history_provides_referent(tmp_path):
    llm = FakeLLM([
        '{"rewritten":"What was the Q3 2025 Northeast revenue figure?",'
        '"confidence":0.92,"ambiguous":false,"referenced_turn_idxs":[1],'
        '"clarifying_question":null}'
    ])
    history = [
        _hist("user", "Show me Q3 2025 revenue by region"),
        _hist("assistant", "Northeast led with $12.4M; Midwest $9.1M; South $8.3M."),
    ]
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")

    out = nodes.contextualize_node(
        _state("What was that revenue number again?", history, llm, session)
    )

    assert out["raw_question"] == "What was that revenue number again?"
    assert out["rewritten_question"] == "What was the Q3 2025 Northeast revenue figure?"
    # The downstream `question` field is the rewritten form so router/sql_gen
    # see a self-contained question.
    assert out["question"] == out["rewritten_question"]
    assert out["history_used"] is True
    assert out["needs_clarification"] is False


def test_routes_to_clarify_when_ambiguous(tmp_path):
    llm = FakeLLM([
        '{"rewritten":"What was that revenue number again?","confidence":0.4,'
        '"ambiguous":true,"referenced_turn_idxs":[1,3],'
        '"clarifying_question":"Which prior analysis — Q3 revenue, top customers, or returns?"}'
    ])
    history = [_hist("user", "Q1"), _hist("assistant", "A1")]
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")

    out = nodes.contextualize_node(
        _state("compare to that", history, llm, session)
    )

    assert out["needs_clarification"] is True
    assert "Which prior analysis" in out["clarifying_question"]
    # No `question` override when routing to clarify.
    assert "question" not in out
    # history_used is False because we never produced a usable rewrite.
    assert out["history_used"] is False


def test_routes_to_clarify_on_low_confidence(tmp_path):
    """confidence < 0.6 routes to clarify even when ambiguous=false."""
    llm = FakeLLM([
        '{"rewritten":"some guess","confidence":0.3,"ambiguous":false,'
        '"referenced_turn_idxs":[],"clarifying_question":"Could you be more specific?"}'
    ])
    history = [_hist("user", "Q1"), _hist("assistant", "A1")]
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")

    out = nodes.contextualize_node(_state("that thing", history, llm, session))

    assert out["needs_clarification"] is True
    assert out["clarifying_question"] == "Could you be more specific?"


def test_falls_back_to_raw_when_llm_errors(tmp_path):
    class BoomLLM:
        def invoke(self, _messages):
            raise RuntimeError("LLM down")

    history = [_hist("user", "prior"), _hist("assistant", "prior-a")]
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")

    out = nodes.contextualize_node(
        _state("compare to that one", history, BoomLLM(), session)
    )
    # Original question survives; never feed garbage downstream.
    assert out["rewritten_question"] == "compare to that one"
    assert out["history_used"] is False
    assert out["needs_clarification"] is False


def test_falls_back_on_malformed_json(tmp_path):
    """Model returns prose instead of JSON — we pass raw through."""
    llm = FakeLLM(["I think you mean the Q3 number from earlier!"])
    history = [_hist("user", "Q1"), _hist("assistant", "A1")]
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")

    out = nodes.contextualize_node(_state("that one", history, llm, session))

    assert out["rewritten_question"] == "that one"
    assert out["needs_clarification"] is False


def test_strips_json_code_fences(tmp_path):
    """Some models wrap JSON in ```json``` fences. We strip and parse."""
    llm = FakeLLM([
        '```json\n{"rewritten":"Q3 revenue by category","confidence":0.9,'
        '"ambiguous":false,"referenced_turn_idxs":[],"clarifying_question":null}\n```'
    ])
    history = [_hist("user", "Q1"), _hist("assistant", "A1")]
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")

    out = nodes.contextualize_node(_state("by category instead", history, llm, session))
    assert out["rewritten_question"] == "Q3 revenue by category"
    assert out["history_used"] is True


def test_history_timestamps_appear_in_prompt(tmp_path):
    """The contextualize prompt must include timestamps so the rewriter
    can resolve relative dates against when the original turn ran."""
    llm = FakeLLM([
        '{"rewritten":"q","confidence":0.95,"ambiguous":false,'
        '"referenced_turn_idxs":[],"clarifying_question":null}'
    ])
    # Specific timestamp: 2026-05-08 09:15 UTC.
    ts = 1778231700
    history = [_hist("user", "Show me Q3 revenue", ts=ts)]
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")

    nodes.contextualize_node(_state("again", history, llm, session))

    # Inspect what was sent to the LLM.
    user_msg = llm.calls[0][1].content  # SystemMessage, then HumanMessage
    assert "2026-05-08" in user_msg
    assert "09:15 UTC" in user_msg
    # Current time is in the prompt too.
    assert "2026-05-10" in user_msg


def test_clarify_node_returns_clarifying_question(tmp_path):
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")
    state = {
        "trace_id": "t",
        "clarifying_question": "Which one — Q3 revenue or top customers?",
        "resources": {"session": session},
    }
    out = nodes.clarify_node(state)
    assert "Which one" in out["final_message"]


def test_clarify_node_falls_back_on_missing_question(tmp_path):
    session = SessionLog(session_id="s", path=tmp_path / "s.jsonl")
    state = {"trace_id": "t", "resources": {"session": session}}
    out = nodes.clarify_node(state)
    assert "clarify" in out["final_message"].lower()
