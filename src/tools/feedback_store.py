"""Feedback capture for the learning loop.

Every successful turn writes a row here. The CLI's /up and /down
commands set the feedback column on the most recent row.
The nightly Curator job reads 👍 rows and promotes them into the Golden
Bucket via scripts/curate.py.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import List, Optional

from src.tools.sqlite_db import connect, query, query_one


@dataclass
class PendingTrio:
    id: int
    trace_id: str
    user_id: str
    question: str
    sql: str
    report: str
    ts: float
    feedback: Optional[str]
    promoted: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PendingTrio":
        return cls(
            id=row["id"],
            trace_id=row["trace_id"],
            user_id=row["user_id"],
            question=row["question"],
            sql=row["sql"],
            report=row["report"],
            ts=row["ts"],
            feedback=row["feedback"],
            promoted=row["promoted"],
        )


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pending_trios (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id    TEXT UNIQUE,
                user_id     TEXT NOT NULL,
                question    TEXT NOT NULL,
                sql         TEXT NOT NULL,
                report      TEXT NOT NULL,
                ts          REAL NOT NULL,
                feedback    TEXT,
                promoted    INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_pending_trios_feedback
                ON pending_trios(feedback);
            """
        )


def record(trace_id: str, user_id: str, question: str, sql: str, report: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pending_trios "
            "(trace_id, user_id, question, sql, report, ts, feedback, promoted) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, 0)",
            (trace_id, user_id, question, sql, report, time.time()),
        )


def set_feedback(trace_id: str, feedback: str) -> bool:
    """feedback in {'up', 'down'}. Returns True if a row was updated."""
    init_db()
    if feedback not in {"up", "down"}:
        raise ValueError(f"feedback must be 'up' or 'down' (got {feedback!r})")
    with connect() as conn:
        cur = conn.execute(
            "UPDATE pending_trios SET feedback = ? WHERE trace_id = ?",
            (feedback, trace_id),
        )
        return cur.rowcount > 0


def list_unpromoted_upvoted() -> List[PendingTrio]:
    init_db()
    rows = query(
        "SELECT * FROM pending_trios WHERE feedback = 'up' AND promoted = 0 "
        "ORDER BY ts ASC"
    )
    return [PendingTrio.from_row(r) for r in rows]


def mark_promoted(trace_ids: List[str]) -> None:
    init_db()
    if not trace_ids:
        return
    placeholders = ",".join("?" * len(trace_ids))
    with connect() as conn:
        conn.execute(
            f"UPDATE pending_trios SET promoted = 1 WHERE trace_id IN ({placeholders})",
            tuple(trace_ids),
        )


def stats() -> dict:
    init_db()
    out = {"total": 0, "up": 0, "down": 0, "promoted": 0}
    rows = query(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN feedback='up' THEN 1 ELSE 0 END) AS up, "
        "SUM(CASE WHEN feedback='down' THEN 1 ELSE 0 END) AS down, "
        "SUM(promoted) AS promoted "
        "FROM pending_trios"
    )
    if rows:
        r = rows[0]
        out = {
            "total": int(r["total"] or 0),
            "up": int(r["up"] or 0),
            "down": int(r["down"] or 0),
            "promoted": int(r["promoted"] or 0),
        }
    return out
