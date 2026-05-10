"""Conversation thread store: persistence, ordering, scoping, CRUD."""
from __future__ import annotations

import time

import pytest

from src.tools import threads_store


# --- creation / lookup -----------------------------------------------------


def test_new_thread_id_is_unique():
    a = threads_store.new_thread_id()
    b = threads_store.new_thread_id()
    assert a != b
    assert len(a) >= 16


def test_ensure_thread_is_idempotent():
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")
    threads_store.ensure_thread(tid, "alice")
    assert threads_store.thread_owner(tid) == "alice"


def test_unknown_thread_owner_returns_none():
    assert threads_store.thread_owner("does-not-exist") is None


def test_get_thread_returns_metadata():
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice", title="Q3 analysis")
    t = threads_store.get_thread(tid)
    assert t is not None
    assert t["title"] == "Q3 analysis"
    assert t["archived"] == 0
    assert t["last_message_at"] is None  # no messages yet


# --- messages ordering + atomicity -----------------------------------------


def test_append_turn_orders_messages_and_increments_idx():
    tid = threads_store.new_thread_id()
    threads_store.append_turn(tid, "alice", "Q1", "A1", trace_id="t1")
    threads_store.append_turn(tid, "alice", "Q2", "A2", trace_id="t2")

    msgs = threads_store.get_recent_messages(tid, n=10)
    # Oldest-first chronological: user1, asst1, user2, asst2.
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert [m["content"] for m in msgs] == ["Q1", "A1", "Q2", "A2"]
    assert threads_store.turn_count(tid) == 4


def test_append_turn_updates_last_message_at():
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")
    before = time.time()
    threads_store.append_turn(tid, "alice", "Q1", "A1")
    t = threads_store.get_thread(tid)
    assert t["last_message_at"] is not None
    assert t["last_message_at"] >= before


def test_get_recent_messages_respects_limit():
    tid = threads_store.new_thread_id()
    for i in range(5):
        threads_store.append_turn(tid, "alice", f"Q{i}", f"A{i}")

    msgs = threads_store.get_recent_messages(tid, n=4)
    assert len(msgs) == 4
    # Last entry overall is the 5th assistant turn (A4).
    assert msgs[-1]["content"] == "A4"
    # Each message carries its created_at — the contextualize prompt
    # needs this to format temporal context.
    assert all("created_at" in m for m in msgs)


def test_messages_carry_timestamp():
    tid = threads_store.new_thread_id()
    threads_store.append_turn(tid, "alice", "Q1", "A1")
    [u, a] = threads_store.get_recent_messages(tid, n=10)
    assert isinstance(u["created_at"], (int, float))
    assert isinstance(a["created_at"], (int, float))
    # User and assistant of the same turn share a timestamp (atomic write).
    assert u["created_at"] == a["created_at"]


# --- isolation -------------------------------------------------------------


def test_threads_are_isolated_per_user():
    t_a = threads_store.new_thread_id()
    t_b = threads_store.new_thread_id()
    threads_store.append_turn(t_a, "alice", "alice-q", "alice-a")
    threads_store.append_turn(t_b, "bob", "bob-q", "bob-a")

    assert threads_store.thread_owner(t_a) == "alice"
    assert threads_store.thread_owner(t_b) == "bob"

    a_msgs = threads_store.get_recent_messages(t_a)
    b_msgs = threads_store.get_recent_messages(t_b)
    assert all(m["content"].startswith("alice") for m in a_msgs)
    assert all(m["content"].startswith("bob") for m in b_msgs)


def test_get_recent_messages_on_empty_thread():
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")
    assert threads_store.get_recent_messages(tid) == []


# --- listing / mutation ----------------------------------------------------


def test_list_for_user_excludes_archived_by_default():
    a1 = threads_store.new_thread_id()
    a2 = threads_store.new_thread_id()
    threads_store.ensure_thread(a1, "alice", title="active")
    threads_store.ensure_thread(a2, "alice", title="to-archive")
    threads_store.set_archived(a2, True)

    listed = threads_store.list_for_user("alice")
    titles = [t["title"] for t in listed]
    assert "active" in titles
    assert "to-archive" not in titles

    listed_all = threads_store.list_for_user("alice", include_archived=True)
    titles_all = [t["title"] for t in listed_all]
    assert "to-archive" in titles_all


def test_list_for_user_sorts_by_recency():
    older = threads_store.new_thread_id()
    newer = threads_store.new_thread_id()
    threads_store.ensure_thread(older, "alice")
    threads_store.append_turn(older, "alice", "old-q", "old-a")
    time.sleep(0.01)
    threads_store.ensure_thread(newer, "alice")
    threads_store.append_turn(newer, "alice", "new-q", "new-a")

    listed = threads_store.list_for_user("alice")
    assert [t["thread_id"] for t in listed] == [newer, older]


def test_list_for_user_does_not_leak_other_users():
    mine = threads_store.new_thread_id()
    other = threads_store.new_thread_id()
    threads_store.ensure_thread(mine, "alice")
    threads_store.ensure_thread(other, "bob")
    listed = threads_store.list_for_user("alice")
    assert all(t["thread_id"] != other for t in listed)


def test_rename_updates_title():
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice", title="old")
    threads_store.rename(tid, "new")
    assert threads_store.get_thread(tid)["title"] == "new"


def test_set_archived_round_trip():
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")
    threads_store.set_archived(tid, True)
    assert threads_store.get_thread(tid)["archived"] == 1
    threads_store.set_archived(tid, False)
    assert threads_store.get_thread(tid)["archived"] == 0


def test_delete_thread_cascades_to_messages():
    tid = threads_store.new_thread_id()
    threads_store.append_turn(tid, "alice", "Q1", "A1")
    assert threads_store.turn_count(tid) == 2
    threads_store.delete_thread(tid)
    assert threads_store.thread_owner(tid) is None
    assert threads_store.turn_count(tid) == 0
