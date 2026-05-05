"""Single-file SQLite helper.

All app-state tables (saved_reports, audit_log, pending_trios, user_prefs)
live in one .db file. Each store module owns its schema and ensures the
table exists at module import.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src import settings

logger = logging.getLogger(__name__)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection with foreign keys + row factory enabled."""
    _ensure_parent(settings.APP_DB_PATH)
    conn = sqlite3.connect(settings.APP_DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def execute(sql: str, params: tuple | dict = ()) -> None:
    with connect() as conn:
        conn.execute(sql, params)


def query(sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall()


def query_one(sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchone()
