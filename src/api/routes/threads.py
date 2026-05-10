"""Conversation thread CRUD.

Per-user scoping is enforced on every endpoint. Cross-user access
returns 404 (not 403) to avoid leaking thread existence.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.identity import Identity, get_identity
from src.api.schemas import (
    CreateThreadRequest,
    ThreadMessage,
    ThreadMessagesResponse,
    ThreadOut,
    ThreadsListResponse,
    UpdateThreadRequest,
)
from src.tools import threads_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["threads"])


def _to_out(row: dict) -> ThreadOut:
    return ThreadOut(
        thread_id=row["thread_id"],
        title=row.get("title"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_message_at=row.get("last_message_at"),
        archived=bool(row.get("archived", 0)),
    )


def _ensure_owned(thread_id: str, user_id: str) -> dict:
    """Return the thread row if owned by `user_id`, else 404.

    Same status code regardless of "doesn't exist" vs. "not yours" —
    the existence of another user's thread should never be observable.
    """
    thread = threads_store.get_thread(thread_id)
    if thread is None or thread["user_id"] != user_id:
        raise HTTPException(404, "thread not found")
    return thread


@router.get("", response_model=ThreadsListResponse)
def list_threads(
    archived: bool = Query(default=False, description="Include archived threads"),
    identity: Identity = Depends(get_identity),
) -> ThreadsListResponse:
    rows = threads_store.list_for_user(identity.user_id, include_archived=archived)
    return ThreadsListResponse(threads=[_to_out(r) for r in rows])


@router.post("", response_model=ThreadOut)
def create_thread(
    req: CreateThreadRequest,
    identity: Identity = Depends(get_identity),
) -> ThreadOut:
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, identity.user_id, title=req.title)
    row = threads_store.get_thread(tid)
    assert row is not None  # just created
    return _to_out(row)


@router.patch("/{thread_id}", response_model=ThreadOut)
def update_thread(
    thread_id: str,
    req: UpdateThreadRequest,
    identity: Identity = Depends(get_identity),
) -> ThreadOut:
    _ensure_owned(thread_id, identity.user_id)
    if req.title is not None:
        title = req.title.strip()
        if not title:
            raise HTTPException(400, "title cannot be blank")
        threads_store.rename(thread_id, title)
    if req.archived is not None:
        threads_store.set_archived(thread_id, req.archived)
    row = threads_store.get_thread(thread_id)
    assert row is not None
    return _to_out(row)


@router.delete("/{thread_id}")
def delete_thread(
    thread_id: str,
    identity: Identity = Depends(get_identity),
) -> dict:
    _ensure_owned(thread_id, identity.user_id)
    threads_store.delete_thread(thread_id)
    return {"deleted": thread_id}


@router.get("/{thread_id}/messages", response_model=ThreadMessagesResponse)
def list_messages(
    thread_id: str,
    identity: Identity = Depends(get_identity),
) -> ThreadMessagesResponse:
    """Replay a thread's full transcript. Used when the user opens an
    investigation from the sidebar."""
    thread = _ensure_owned(thread_id, identity.user_id)
    rows = threads_store.get_all_messages(thread_id)
    return ThreadMessagesResponse(
        thread_id=thread_id,
        title=thread.get("title"),
        messages=[ThreadMessage(**r) for r in rows],
    )
