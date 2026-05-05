"""Shared fixtures: redirect APP_DB_PATH to a temp file for store tests."""
from __future__ import annotations

import pytest

from src import settings


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point settings.APP_DB_PATH at a fresh per-test SQLite file.

    Autouse so no test ever touches the real data/app.db.
    """
    db = tmp_path / "test_app.db"
    monkeypatch.setattr(settings, "APP_DB_PATH", db)
    return db
