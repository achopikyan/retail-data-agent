"""Process-wide singletons.

We construct heavy resources (BigQuery client, Gemini wrapper,
GoldenBucket, compiled graph) once at process startup, then inject them
into route handlers. The CLI does the same.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict

from src.graph.builder import build_graph
from src.llm.gemini import GeminiLLM
from src.tools import feedback_store, prefs_store, reports_store, threads_store
from src.tools.bq import BigQueryRunner, get_schema_summary
from src.tools.golden_bucket import GoldenBucket
from src import settings

logger = logging.getLogger(__name__)


class Resources:
    """Lazily-initialized container for shared agent resources."""

    _lock = threading.Lock()
    _instance: "Resources | None" = None

    def __init__(self) -> None:
        logger.info("Initializing API resources")
        self.bq = BigQueryRunner(project_id=settings.GOOGLE_CLOUD_PROJECT or None)
        self.schema_summary = get_schema_summary(self.bq)
        self.golden_bucket = GoldenBucket.load()
        self.llm = GeminiLLM()
        self.graph = build_graph()
        # Make sure all SQLite tables exist (idempotent).
        reports_store.init_db()
        feedback_store.init_db()
        prefs_store.init_db()
        threads_store.init_db()
        logger.info("API resources ready")

    @classmethod
    def get(cls) -> "Resources":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance


def get_resources() -> Resources:
    return Resources.get()


def base_graph_resources(session_log) -> Dict[str, Any]:
    r = get_resources()
    return {
        "bq": r.bq,
        "golden_bucket": r.golden_bucket,
        "llm": r.llm,
        "schema_summary": r.schema_summary,
        "session": session_log,
    }
