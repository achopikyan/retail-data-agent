"""Per-user preferences (table | bullets | prose, default time window, etc.).

Updated explicitly via `/prefs set k=v` or implicitly when the router
detects a format hint in the user's question.
Read by the Reporter node and injected into the prompt.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

from src.tools.sqlite_db import connect, query, query_one


# Whitelisted keys to prevent typos turning into silent no-ops.
ALLOWED_KEYS = {"report_format", "default_time_window", "preferred_currency"}


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id     TEXT NOT NULL,
                key         TEXT NOT NULL,
                value       TEXT NOT NULL,
                updated_at  REAL NOT NULL,
                PRIMARY KEY (user_id, key)
            );
            """
        )


def set_pref(user_id: str, key: str, value: str) -> None:
    init_db()
    if key not in ALLOWED_KEYS:
        raise ValueError(f"unknown pref key: {key!r}. Allowed: {sorted(ALLOWED_KEYS)}")
    with connect() as conn:
        conn.execute(
            "INSERT INTO user_prefs (user_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (user_id, key, value, time.time()),
        )


def get_prefs(user_id: str) -> Dict[str, str]:
    init_db()
    rows = query("SELECT key, value FROM user_prefs WHERE user_id = ?", (user_id,))
    return {r["key"]: r["value"] for r in rows}


def get_pref(user_id: str, key: str) -> Optional[str]:
    init_db()
    row = query_one(
        "SELECT value FROM user_prefs WHERE user_id = ? AND key = ?",
        (user_id, key),
    )
    return row["value"] if row else None


def render_for_prompt(user_id: str) -> str:
    """Human-readable line for injection into the Reporter prompt."""
    prefs = get_prefs(user_id)
    if not prefs:
        return ""
    parts = [f"{k}={v}" for k, v in sorted(prefs.items())]
    return "User preferences (apply when not in conflict with persona): " + ", ".join(parts)
