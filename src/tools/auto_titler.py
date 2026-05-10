"""Generate a short thread title from the first turn's question.

Fires once per thread, immediately after the first successful report,
and only when `threads.title` is empty. Never overwrites a user-set
title. Failures are silent — a missing title is harmless.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from src.tools import threads_store

logger = logging.getLogger(__name__)


_TITLER_SYS = """You produce a 4-6 word title for a data-analysis thread.
- Output ONLY the title text. No quotes, no markdown, no preamble.
- Use Title Case. No trailing punctuation.
- Capture the topic, not the verb form (e.g. "Q3 Revenue by Region", not "Show me Q3 revenue").
"""


def _sanitize(raw: str) -> str:
    """Take first non-empty line, strip quotes/punctuation, cap length."""
    first = next((ln.strip() for ln in (raw or "").splitlines() if ln.strip()), "")
    first = first.strip('"').strip("'").strip()
    # Drop common prefixes models slip in despite instructions.
    first = re.sub(r"^(title:|the\s+title\s+is\s*:?)\s*", "", first, flags=re.IGNORECASE)
    first = first.strip().rstrip(".")
    if len(first) > 80:
        first = first[:80].rstrip()
    return first


def maybe_set_title(
    thread_id: str,
    user_question: str,
    llm,
) -> Optional[str]:
    """If thread has no title, generate one and persist it.

    Returns the title that ended up on the thread (or None on failure).
    Failure is non-fatal — the caller logs and moves on.
    """
    thread = threads_store.get_thread(thread_id)
    if thread is None:
        return None
    if (thread.get("title") or "").strip():
        return thread["title"]

    try:
        resp = llm.invoke(
            [
                SystemMessage(content=_TITLER_SYS),
                HumanMessage(content=f"User question: {user_question}\n\nReturn the title only."),
            ]
        )
        text = resp.content if hasattr(resp, "content") else str(resp)
        title = _sanitize(text)
        if not title:
            return None
        threads_store.rename(thread_id, title)
        return title
    except Exception as e:  # noqa: BLE001
        logger.warning("auto-titler failed for thread %s: %s", thread_id, e)
        return None
