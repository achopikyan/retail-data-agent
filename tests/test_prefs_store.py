"""User preferences store: set, get, render, key whitelist."""
from __future__ import annotations

import pytest

from src.tools import prefs_store


def test_set_and_get(tmp_db):
    prefs_store.set_pref("alice", "report_format", "table")
    assert prefs_store.get_pref("alice", "report_format") == "table"


def test_upsert_overwrites(tmp_db):
    prefs_store.set_pref("alice", "report_format", "table")
    prefs_store.set_pref("alice", "report_format", "bullets")
    assert prefs_store.get_pref("alice", "report_format") == "bullets"


def test_per_user_isolation(tmp_db):
    prefs_store.set_pref("alice", "report_format", "table")
    prefs_store.set_pref("bob", "report_format", "prose")
    assert prefs_store.get_pref("alice", "report_format") == "table"
    assert prefs_store.get_pref("bob", "report_format") == "prose"


def test_render_for_prompt(tmp_db):
    assert prefs_store.render_for_prompt("alice") == ""
    prefs_store.set_pref("alice", "report_format", "table")
    out = prefs_store.render_for_prompt("alice")
    assert "report_format=table" in out


def test_unknown_key_rejected(tmp_db):
    with pytest.raises(ValueError):
        prefs_store.set_pref("alice", "favorite_color", "blue")
