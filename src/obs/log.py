"""Observability: structured JSON logger + per-session JSONL replay file
+ in-process counters.

The CLI creates one session_<id>.jsonl per run. Every node emits
node-start / node-end events containing trace_id, latency_ms, and a
small payload (truncated). This file is the deep-dive artifact for
debugging "what went wrong on this turn".
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from src import settings


# --- counters --------------------------------------------------------------

_COUNTERS: Counter[str] = Counter()


def incr(metric: str, n: int = 1) -> None:
    _COUNTERS[metric] += n


def counters_snapshot() -> Dict[str, int]:
    return dict(_COUNTERS)


# --- session jsonl writer --------------------------------------------------


class SessionLog:
    def __init__(self, session_id: Optional[str] = None, path: Optional[Path] = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        if path is not None:
            self.path: Path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
            self.path = settings.LOG_DIR / f"session_{self.session_id}.jsonl"
        self._fh = open(self.path, "a", encoding="utf-8", buffering=1)

    def event(self, event: str, **fields: Any) -> None:
        record = {
            "ts": time.time(),
            "session_id": self.session_id,
            "event": event,
            **{k: _truncate(v) for k, v in fields.items()},
        }
        self._fh.write(json.dumps(record, default=str) + "\n")

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def _truncate(v: Any, limit: int = 1500) -> Any:
    if isinstance(v, str) and len(v) > limit:
        return v[:limit] + f"...<+{len(v) - limit} chars>"
    return v


@contextmanager
def timed(session: SessionLog, node: str, trace_id: str, **extra: Any):
    t0 = time.perf_counter()
    session.event("node_start", node=node, trace_id=trace_id, **extra)
    incr(f"node.{node}.start")
    try:
        yield
    except Exception as e:  # noqa: BLE001
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        session.event(
            "node_error",
            node=node,
            trace_id=trace_id,
            latency_ms=latency_ms,
            error=str(e),
        )
        incr(f"node.{node}.error")
        raise
    else:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        session.event(
            "node_end", node=node, trace_id=trace_id, latency_ms=latency_ms
        )
        incr(f"node.{node}.ok")


# --- module-level logger ---------------------------------------------------


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)
