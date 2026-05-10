"""CLI thread commands. Drives `cmd_thread` / `cmd_threads` directly
and asserts on the store state + captured stdout.
"""
from __future__ import annotations

import builtins
from typing import List

import pytest

from src import cli
from src.cli import Session, cmd_thread, cmd_threads
from src.tools import threads_store


@pytest.fixture
def session() -> Session:
    return Session(current_user="alice")


# --- /thread new -----------------------------------------------------------


def test_new_creates_and_switches(session, capsys):
    cmd_thread(session, "new Q3 analysis")
    assert session.thread_id is not None
    t = threads_store.get_thread(session.thread_id)
    assert t["title"] == "Q3 analysis"
    out = capsys.readouterr().out
    assert "created + switched" in out


def test_new_without_title(session):
    cmd_thread(session, "new")
    t = threads_store.get_thread(session.thread_id)
    assert t["title"] is None


# --- /thread (no subcommand) ----------------------------------------------


def test_show_active_when_none(session, capsys):
    cmd_thread(session, "")
    assert "no active thread" in capsys.readouterr().out


def test_show_active_with_thread(session, capsys):
    cmd_thread(session, "new Q3 analysis")
    threads_store.append_turn(session.thread_id, "alice", "Q1", "A1")
    capsys.readouterr()  # discard the new-thread output

    cmd_thread(session, "")
    out = capsys.readouterr().out
    assert "Q3 analysis" in out
    assert "turns: 2" in out


# --- /thread switch -------------------------------------------------------


def test_switch_by_full_id(session):
    cmd_thread(session, "new t1")
    t1 = session.thread_id
    cmd_thread(session, "new t2")
    t2 = session.thread_id
    assert t1 != t2

    cmd_thread(session, f"switch {t1}")
    assert session.thread_id == t1


def test_switch_by_unique_prefix(session):
    cmd_thread(session, "new t1")
    t1 = session.thread_id
    cmd_thread(session, "new t2")

    # 8-char prefix is overwhelmingly unique.
    cmd_thread(session, f"switch {t1[:8]}")
    assert session.thread_id == t1


def test_switch_unknown_id_keeps_active(session, capsys):
    cmd_thread(session, "new only")
    original = session.thread_id
    cmd_thread(session, "switch deadbeef-not-a-real-id")
    assert session.thread_id == original
    assert "no unique thread" in capsys.readouterr().out


def test_switch_does_not_leak_other_users(session, capsys):
    """A switch arg matching another user's thread must NOT switch to it."""
    other = threads_store.new_thread_id()
    threads_store.ensure_thread(other, "bob", title="bob's secret")
    cmd_thread(session, f"switch {other}")
    assert session.thread_id != other
    assert "no unique thread" in capsys.readouterr().out


# --- /thread rename -------------------------------------------------------


def test_rename(session):
    cmd_thread(session, "new old")
    cmd_thread(session, "rename new title")
    assert threads_store.get_thread(session.thread_id)["title"] == "new title"


def test_rename_with_no_active_thread(session, capsys):
    cmd_thread(session, "rename anything")
    assert "no active thread" in capsys.readouterr().out


# --- /thread archive ------------------------------------------------------


def test_archive_active_clears_session_thread(session):
    cmd_thread(session, "new x")
    tid = session.thread_id
    cmd_thread(session, "archive")
    assert threads_store.get_thread(tid)["archived"] == 1
    # Archiving the active thread clears it so next question starts fresh.
    assert session.thread_id is None


def test_archive_specific_id_keeps_active(session):
    cmd_thread(session, "new keep")
    keep = session.thread_id
    cmd_thread(session, "new archive-me")
    archive_target = session.thread_id

    cmd_thread(session, f"switch {keep}")
    cmd_thread(session, f"archive {archive_target}")

    assert session.thread_id == keep
    assert threads_store.get_thread(archive_target)["archived"] == 1
    assert threads_store.get_thread(keep)["archived"] == 0


# --- /thread delete -------------------------------------------------------


def test_delete_with_confirmation(session, monkeypatch):
    cmd_thread(session, "new doomed")
    tid = session.thread_id
    monkeypatch.setattr(builtins, "input", lambda _: "y")
    cmd_thread(session, f"delete {tid}")
    assert threads_store.get_thread(tid) is None
    assert session.thread_id is None


def test_delete_cancelled_keeps_thread(session, monkeypatch, capsys):
    cmd_thread(session, "new keepme")
    tid = session.thread_id
    monkeypatch.setattr(builtins, "input", lambda _: "n")
    cmd_thread(session, f"delete {tid}")
    assert threads_store.get_thread(tid) is not None
    assert session.thread_id == tid


# --- /threads -------------------------------------------------------------


def test_threads_lists_active_only_by_default(session, capsys):
    cmd_thread(session, "new visible")
    visible = session.thread_id
    cmd_thread(session, "new hidden")
    hidden = session.thread_id
    cmd_thread(session, f"archive {hidden}")
    capsys.readouterr()

    cmd_threads(session, "")
    out = capsys.readouterr().out
    assert "visible" in out
    assert "hidden" not in out


def test_threads_with_archived_flag(session, capsys):
    cmd_thread(session, "new visible")
    cmd_thread(session, "new hidden")
    cmd_thread(session, "archive")  # archives 'hidden' (active)
    capsys.readouterr()

    cmd_threads(session, "--archived")
    out = capsys.readouterr().out
    assert "hidden" in out
    assert "archived" in out


def test_threads_marks_active_with_asterisk(session, capsys):
    cmd_thread(session, "new only")
    capsys.readouterr()
    cmd_threads(session, "")
    out = capsys.readouterr().out
    assert "*" in out
