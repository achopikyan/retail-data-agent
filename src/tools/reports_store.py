"""Saved Reports library + audit log.

Tables:
    saved_reports(id, owner_id, title, body, created_at, updated_at)
    audit_log   (id, ts, actor_id, action, target_ids, reason, trace_id)

Ownership rule: a manager can only delete their own reports unless they
have the gdpr_officer role. Cross-user destructive ops require an
additional confirmation step at the CLI layer (typing the report count).
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import List, Optional

from src.tools.sqlite_db import connect, execute, query, query_one

logger = logging.getLogger(__name__)


GDPR_ROLE = "gdpr_officer"


@dataclass
class Report:
    id: int
    owner_id: str
    title: str
    body: str
    created_at: float
    updated_at: float

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Report":
        return cls(
            id=row["id"],
            owner_id=row["owner_id"],
            title=row["title"],
            body=row["body"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS saved_reports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id    TEXT NOT NULL,
                title       TEXT NOT NULL,
                body        TEXT NOT NULL,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_saved_reports_owner
                ON saved_reports(owner_id);

            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL NOT NULL,
                actor_id    TEXT NOT NULL,
                action      TEXT NOT NULL,
                target_ids  TEXT NOT NULL,
                reason      TEXT,
                trace_id    TEXT
            );
            """
        )


def save(owner_id: str, title: str, body: str) -> int:
    init_db()
    now = time.time()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO saved_reports (owner_id, title, body, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (owner_id, title, body, now, now),
        )
        return int(cur.lastrowid)


def list_for(owner_id: Optional[str] = None) -> List[Report]:
    init_db()
    if owner_id is None:
        rows = query("SELECT * FROM saved_reports ORDER BY created_at DESC")
    else:
        rows = query(
            "SELECT * FROM saved_reports WHERE owner_id = ? ORDER BY created_at DESC",
            (owner_id,),
        )
    return [Report.from_row(r) for r in rows]


def get(report_id: int) -> Optional[Report]:
    init_db()
    row = query_one("SELECT * FROM saved_reports WHERE id = ?", (report_id,))
    return Report.from_row(row) if row else None


def find_matching(substring: str, owner_id: Optional[str] = None) -> List[Report]:
    """Find reports whose title or body contains the substring (case-insensitive)."""
    init_db()
    needle = f"%{substring}%"
    if owner_id is None:
        rows = query(
            "SELECT * FROM saved_reports "
            "WHERE LOWER(title) LIKE LOWER(?) OR LOWER(body) LIKE LOWER(?) "
            "ORDER BY created_at DESC",
            (needle, needle),
        )
    else:
        rows = query(
            "SELECT * FROM saved_reports WHERE owner_id = ? AND "
            "(LOWER(title) LIKE LOWER(?) OR LOWER(body) LIKE LOWER(?)) "
            "ORDER BY created_at DESC",
            (owner_id, needle, needle),
        )
    return [Report.from_row(r) for r in rows]


def delete_ids(
    target_ids: List[int],
    actor_id: str,
    actor_role: str = "manager",
    reason: str = "",
    trace_id: Optional[str] = None,
) -> int:
    """Delete given report IDs, enforcing ownership.

    Returns the number of rows deleted. Audit row is always written.
    Raises PermissionError if the actor tries to delete a report they
    don't own and isn't a gdpr_officer.
    """
    init_db()
    if not target_ids:
        return 0

    # Ownership check
    placeholders = ",".join("?" * len(target_ids))
    rows = query(
        f"SELECT id, owner_id FROM saved_reports WHERE id IN ({placeholders})",
        tuple(target_ids),
    )
    if actor_role != GDPR_ROLE:
        not_owned = [r["id"] for r in rows if r["owner_id"] != actor_id]
        if not_owned:
            raise PermissionError(
                f"Cannot delete reports not owned by {actor_id}: {not_owned}. "
                f"Cross-user delete requires the {GDPR_ROLE} role."
            )

    with connect() as conn:
        cur = conn.execute(
            f"DELETE FROM saved_reports WHERE id IN ({placeholders})",
            tuple(target_ids),
        )
        deleted = cur.rowcount
        conn.execute(
            "INSERT INTO audit_log (ts, actor_id, action, target_ids, reason, trace_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                time.time(),
                actor_id,
                "delete" if actor_role != GDPR_ROLE else "delete_gdpr",
                ",".join(str(i) for i in target_ids),
                reason,
                trace_id,
            ),
        )
    return int(deleted)


def audit_recent(limit: int = 20) -> List[sqlite3.Row]:
    init_db()
    return query("SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,))
