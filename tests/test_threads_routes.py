"""Thread CRUD endpoints. Tests the per-user scoping invariants
(404 on cross-user access) which are the most security-relevant
behavior of this surface.

We mount the threads router on a bare FastAPI app to avoid spinning
up the full resources singleton (BQ + LLM) that the main app builds
at import time.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.threads import router as threads_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(threads_router)
    return TestClient(app)


def _hdrs(user_id: str = "alice", role: str = "manager") -> dict:
    return {"X-User-Id": user_id, "X-User-Role": role}


# --- list / create ---------------------------------------------------------


def test_empty_list(client):
    r = client.get("/api/threads", headers=_hdrs())
    assert r.status_code == 200
    assert r.json() == {"threads": []}


def test_create_then_list(client):
    r = client.post("/api/threads", json={"title": "Q3 analysis"}, headers=_hdrs())
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Q3 analysis"
    assert body["archived"] is False
    tid = body["thread_id"]

    r2 = client.get("/api/threads", headers=_hdrs())
    assert r2.status_code == 200
    threads = r2.json()["threads"]
    assert len(threads) == 1
    assert threads[0]["thread_id"] == tid


def test_create_without_title(client):
    r = client.post("/api/threads", json={}, headers=_hdrs())
    assert r.status_code == 200
    assert r.json()["title"] is None


# --- per-user scoping (the security invariants) ---------------------------


def test_other_user_threads_are_invisible(client):
    client.post("/api/threads", json={"title": "alice's"}, headers=_hdrs("alice"))
    r = client.get("/api/threads", headers=_hdrs("bob"))
    assert r.status_code == 200
    assert r.json()["threads"] == []


def test_cross_user_patch_returns_404_not_403(client):
    """A 403 would leak the existence of someone else's thread.
    The route must return 404 to keep ownership invisible.
    """
    created = client.post("/api/threads", json={"title": "x"}, headers=_hdrs("alice")).json()
    tid = created["thread_id"]

    r = client.patch(f"/api/threads/{tid}", json={"title": "y"}, headers=_hdrs("bob"))
    assert r.status_code == 404


def test_cross_user_delete_returns_404(client):
    created = client.post("/api/threads", json={"title": "x"}, headers=_hdrs("alice")).json()
    tid = created["thread_id"]

    r = client.delete(f"/api/threads/{tid}", headers=_hdrs("bob"))
    assert r.status_code == 404
    # And alice's thread is still there.
    listed = client.get("/api/threads", headers=_hdrs("alice")).json()["threads"]
    assert any(t["thread_id"] == tid for t in listed)


def test_unknown_thread_returns_404(client):
    r = client.patch(
        "/api/threads/does-not-exist", json={"title": "x"}, headers=_hdrs()
    )
    assert r.status_code == 404


# --- update / archive / delete --------------------------------------------


def test_rename_thread(client):
    created = client.post("/api/threads", json={"title": "old"}, headers=_hdrs()).json()
    tid = created["thread_id"]
    r = client.patch(f"/api/threads/{tid}", json={"title": "new"}, headers=_hdrs())
    assert r.status_code == 200
    assert r.json()["title"] == "new"


def test_blank_title_rejected(client):
    created = client.post("/api/threads", json={"title": "old"}, headers=_hdrs()).json()
    tid = created["thread_id"]
    r = client.patch(f"/api/threads/{tid}", json={"title": "   "}, headers=_hdrs())
    assert r.status_code == 400


def test_archive_then_excluded_by_default(client):
    created = client.post("/api/threads", json={"title": "to-archive"}, headers=_hdrs()).json()
    tid = created["thread_id"]
    r = client.patch(f"/api/threads/{tid}", json={"archived": True}, headers=_hdrs())
    assert r.status_code == 200
    assert r.json()["archived"] is True

    listed = client.get("/api/threads", headers=_hdrs()).json()["threads"]
    assert all(t["thread_id"] != tid for t in listed)

    listed_all = client.get(
        "/api/threads", params={"archived": True}, headers=_hdrs()
    ).json()["threads"]
    assert any(t["thread_id"] == tid for t in listed_all)


def test_unarchive(client):
    created = client.post("/api/threads", json={"title": "x"}, headers=_hdrs()).json()
    tid = created["thread_id"]
    client.patch(f"/api/threads/{tid}", json={"archived": True}, headers=_hdrs())
    r = client.patch(f"/api/threads/{tid}", json={"archived": False}, headers=_hdrs())
    assert r.status_code == 200
    assert r.json()["archived"] is False


def test_delete_removes_thread(client):
    created = client.post("/api/threads", json={"title": "x"}, headers=_hdrs()).json()
    tid = created["thread_id"]
    r = client.delete(f"/api/threads/{tid}", headers=_hdrs())
    assert r.status_code == 200
    assert r.json() == {"deleted": tid}

    listed = client.get("/api/threads", headers=_hdrs()).json()["threads"]
    assert listed == []


# --- messages endpoint (used to replay a thread when user clicks it) ----


def test_list_messages_empty_thread(client):
    created = client.post("/api/threads", json={"title": "x"}, headers=_hdrs()).json()
    tid = created["thread_id"]
    r = client.get(f"/api/threads/{tid}/messages", headers=_hdrs())
    assert r.status_code == 200
    assert r.json() == {"thread_id": tid, "title": "x", "messages": []}


def test_list_messages_returns_chronological_pairs(client):
    from src.tools import threads_store

    created = client.post("/api/threads", json={"title": "x"}, headers=_hdrs()).json()
    tid = created["thread_id"]
    threads_store.append_turn(tid, "alice", "Q1", "A1", trace_id="t1")
    threads_store.append_turn(tid, "alice", "Q2", "A2", trace_id="t2")

    r = client.get(f"/api/threads/{tid}/messages", headers=_hdrs())
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 4
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert [m["content"] for m in msgs] == ["Q1", "A1", "Q2", "A2"]
    # Sequential turn_idx
    assert [m["turn_idx"] for m in msgs] == [0, 1, 2, 3]


def test_list_messages_cross_user_returns_404(client):
    created = client.post("/api/threads", json={"title": "x"}, headers=_hdrs("alice")).json()
    tid = created["thread_id"]
    r = client.get(f"/api/threads/{tid}/messages", headers=_hdrs("bob"))
    assert r.status_code == 404
