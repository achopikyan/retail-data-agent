"""Auto-titler: fires once, never overwrites a user-set title,
silent on failure.
"""
from __future__ import annotations

from typing import List

import pytest
from langchain_core.messages import AIMessage

from src.tools import auto_titler, threads_store


class FakeLLM:
    def __init__(self, responses: List[str]):
        self._responses = list(responses)
        self.calls: List[list] = []

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self._responses.pop(0) if self._responses else "")


def test_sets_title_when_empty():
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")
    llm = FakeLLM(["Q3 Revenue by Region"])

    title = auto_titler.maybe_set_title(tid, "Show me Q3 2025 revenue by region", llm)

    assert title == "Q3 Revenue by Region"
    assert threads_store.get_thread(tid)["title"] == "Q3 Revenue by Region"
    assert len(llm.calls) == 1


def test_does_not_overwrite_existing_title():
    """If user manually named it, never replace."""
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice", title="My Custom Title")
    llm = FakeLLM(["Auto Generated Title"])

    title = auto_titler.maybe_set_title(tid, "anything", llm)

    # Returned title is the existing one; no LLM call was made.
    assert title == "My Custom Title"
    assert llm.calls == []
    assert threads_store.get_thread(tid)["title"] == "My Custom Title"


def test_strips_quotes_and_prefixes():
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")
    llm = FakeLLM(['"Top Customers Analysis"\n(extra)'])

    title = auto_titler.maybe_set_title(tid, "Top customers", llm)

    assert title == "Top Customers Analysis"


def test_handles_title_prefix_from_model():
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")
    llm = FakeLLM(["Title: Customer Spend Analysis"])

    title = auto_titler.maybe_set_title(tid, "Top customers", llm)

    assert title == "Customer Spend Analysis"


def test_silent_on_llm_failure():
    class BoomLLM:
        def invoke(self, _messages):
            raise RuntimeError("LLM down")

    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")
    title = auto_titler.maybe_set_title(tid, "anything", BoomLLM())

    # Returns None, leaves title unset; caller treats this as harmless.
    assert title is None
    assert threads_store.get_thread(tid)["title"] is None


def test_silent_on_blank_response():
    tid = threads_store.new_thread_id()
    threads_store.ensure_thread(tid, "alice")
    llm = FakeLLM([""])

    title = auto_titler.maybe_set_title(tid, "x", llm)
    assert title is None


def test_returns_none_for_unknown_thread():
    llm = FakeLLM(["Should not be called"])
    title = auto_titler.maybe_set_title("does-not-exist", "x", llm)
    assert title is None
    assert llm.calls == []
