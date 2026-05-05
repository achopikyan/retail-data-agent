"""Pending Trios feedback store: record, set_feedback, list_unpromoted_upvoted."""
from __future__ import annotations

import pytest

from src.tools import feedback_store


def test_record_and_feedback(tmp_db):
    feedback_store.record("trace1", "alice", "Q?", "SELECT 1", "report")
    assert feedback_store.set_feedback("trace1", "up") is True
    rows = feedback_store.list_unpromoted_upvoted()
    assert len(rows) == 1
    assert rows[0].trace_id == "trace1"
    assert rows[0].feedback == "up"


def test_downvote_excluded_from_unpromoted(tmp_db):
    feedback_store.record("t1", "alice", "Q?", "SQL", "R")
    feedback_store.set_feedback("t1", "down")
    assert feedback_store.list_unpromoted_upvoted() == []


def test_promotion_marker(tmp_db):
    feedback_store.record("t1", "alice", "Q?", "SQL", "R")
    feedback_store.set_feedback("t1", "up")
    feedback_store.mark_promoted(["t1"])
    assert feedback_store.list_unpromoted_upvoted() == []


def test_invalid_feedback_rejected(tmp_db):
    feedback_store.record("t1", "alice", "Q?", "SQL", "R")
    with pytest.raises(ValueError):
        feedback_store.set_feedback("t1", "maybe")


def test_stats(tmp_db):
    feedback_store.record("a", "u", "Q", "S", "R")
    feedback_store.record("b", "u", "Q", "S", "R")
    feedback_store.record("c", "u", "Q", "S", "R")
    feedback_store.set_feedback("a", "up")
    feedback_store.set_feedback("b", "down")
    s = feedback_store.stats()
    assert s["total"] == 3
    assert s["up"] == 1
    assert s["down"] == 1
    assert s["promoted"] == 0
