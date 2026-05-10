"""Conversation threads + per-turn messages.

Production-shaped interface so the backend can be swapped to Postgres
(threads + messages tables, RLS by user_id, pgvector for old-turn
retrieval) without touching the graph or the routes. Today: sqlite.

Design choices:
- Threads are first-class user-managed objects (per-investigation, not
  per-session). They persist indefinitely; users name + archive + delete
  them explicitly.
- Messages are append-only (turn_idx monotonic). No edits, no deletes
  except cascading from the thread.
- Refusals/errors/clarifications are NEVER appended — only successful
  analytical reports — to keep follow-up rewrites grounded in real
  reports.
- Per-user scoping is enforced at the route layer; this module exposes
  `thread_owner()` so callers can 404 on cross-user access (existence
  is not leaked).
"""
from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional

from src.tools.sqlite_db import connect, query, query_one


ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS threads (
                thread_id        TEXT PRIMARY KEY,
                user_id          TEXT NOT NULL,
                title            TEXT,
                created_at       REAL NOT NULL,
                updated_at       REAL NOT NULL,
                last_message_at  REAL,
                archived         INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_threads_user_active
                ON threads (user_id, archived, last_message_at DESC);

            CREATE TABLE IF NOT EXISTS thread_messages (
                message_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id   TEXT NOT NULL,
                turn_idx    INTEGER NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                trace_id    TEXT,
                created_at  REAL NOT NULL,
                FOREIGN KEY (thread_id) REFERENCES threads(thread_id)
            );
            CREATE INDEX IF NOT EXISTS idx_messages_thread
                ON thread_messages (thread_id, turn_idx);
            """
        )


# --- create / lookup -------------------------------------------------------


def new_thread_id() -> str:
    """Opaque UUID. Sequential ids would leak ordering across users."""
    return uuid.uuid4().hex


def ensure_thread(thread_id: str, user_id: str, title: Optional[str] = None) -> None:
    """Create the thread row if missing. Idempotent.

    Caller is responsible for verifying that `thread_id` either belongs
    to `user_id` or is brand new (use `thread_owner()` first).
    """
    init_db()
    now = time.time()
    with connect() as conn:
        conn.execute(
            "INSERT INTO threads (thread_id, user_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(thread_id) DO NOTHING",
            (thread_id, user_id, title, now, now),
        )


def thread_owner(thread_id: str) -> Optional[str]:
    """Return `user_id` that owns `thread_id`, or None if the thread doesn't exist."""
    init_db()
    row = query_one("SELECT user_id FROM threads WHERE thread_id = ?", (thread_id,))
    return row["user_id"] if row else None


def get_thread(thread_id: str) -> Optional[Dict]:
    init_db()
    row = query_one(
        "SELECT thread_id, user_id, title, created_at, updated_at, "
        "       last_message_at, archived "
        "FROM threads WHERE thread_id = ?",
        (thread_id,),
    )
    return dict(row) if row else None


# --- list / mutate ---------------------------------------------------------


def list_for_user(user_id: str, include_archived: bool = False) -> List[Dict]:
    init_db()
    sql = (
        "SELECT thread_id, title, created_at, updated_at, last_message_at, archived "
        "FROM threads WHERE user_id = ?"
    )
    params: tuple = (user_id,)
    if not include_archived:
        sql += " AND archived = 0"
    # Sort by activity, newest first; threads with no messages yet sort
    # by updated_at as a fallback.
    sql += " ORDER BY COALESCE(last_message_at, updated_at) DESC"
    rows = query(sql, params)
    return [dict(r) for r in rows]


def rename(thread_id: str, title: str) -> None:
    init_db()
    now = time.time()
    with connect() as conn:
        conn.execute(
            "UPDATE threads SET title = ?, updated_at = ? WHERE thread_id = ?",
            (title, now, thread_id),
        )


def set_archived(thread_id: str, archived: bool) -> None:
    init_db()
    now = time.time()
    with connect() as conn:
        conn.execute(
            "UPDATE threads SET archived = ?, updated_at = ? WHERE thread_id = ?",
            (1 if archived else 0, now, thread_id),
        )


def delete_thread(thread_id: str) -> None:
    """Hard delete: cascades to messages. Caller must verify ownership."""
    init_db()
    with connect() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM thread_messages WHERE thread_id = ?", (thread_id,))
            conn.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


# --- messages --------------------------------------------------------------


def get_recent_messages(thread_id: str, n: int = 10) -> List[Dict]:
    """Return up to `n` most recent messages, oldest first.

    Each message: {"role", "content", "created_at"}.
    Timestamps included so the contextualize prompt can resolve relative
    dates ("yesterday's") against when the original turn ran.
    """
    init_db()
    rows = query(
        "SELECT role, content, created_at FROM thread_messages "
        "WHERE thread_id = ? ORDER BY turn_idx DESC LIMIT ?",
        (thread_id, n),
    )
    return [
        {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
        for r in reversed(rows)
    ]


def append_turn(
    thread_id: str,
    user_id: str,
    user_question: str,
    assistant_response: str,
    trace_id: Optional[str] = None,
) -> None:
    """Append (user_msg, assistant_msg) atomically.

    A turn is either fully persisted or not at all — history must never
    show a question without its answer.
    """
    init_db()
    ensure_thread(thread_id, user_id)
    now = time.time()
    with connect() as conn:
        conn.execute("BEGIN")
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(turn_idx), -1) AS m FROM thread_messages "
                "WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            next_idx = (row["m"] if row else -1) + 1
            conn.execute(
                "INSERT INTO thread_messages "
                "  (thread_id, turn_idx, role, content, trace_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (thread_id, next_idx, ROLE_USER, user_question, trace_id, now),
            )
            conn.execute(
                "INSERT INTO thread_messages "
                "  (thread_id, turn_idx, role, content, trace_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (thread_id, next_idx + 1, ROLE_ASSISTANT, assistant_response, trace_id, now),
            )
            conn.execute(
                "UPDATE threads SET updated_at = ?, last_message_at = ? "
                "WHERE thread_id = ?",
                (now, now, thread_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def get_all_messages(thread_id: str) -> List[Dict]:
    """Full transcript for a thread, oldest first. For UI replay when
    a user opens a thread from the sidebar (vs. the last-N window the
    contextualize node uses)."""
    init_db()
    rows = query(
        "SELECT role, content, trace_id, created_at, turn_idx "
        "FROM thread_messages WHERE thread_id = ? ORDER BY turn_idx ASC",
        (thread_id,),
    )
    return [
        {
            "role": r["role"],
            "content": r["content"],
            "trace_id": r["trace_id"],
            "created_at": r["created_at"],
            "turn_idx": r["turn_idx"],
        }
        for r in rows
    ]


def turn_count(thread_id: str) -> int:
    init_db()
    row = query_one(
        "SELECT COUNT(*) AS c FROM thread_messages WHERE thread_id = ?",
        (thread_id,),
    )
    return int(row["c"]) if row else 0
