"""Pretty-print a session JSONL for debugging.

Usage:
    python -m scripts.replay <session_id_or_path>
    python -m scripts.replay --latest
    python -m scripts.replay 8c4f1a2bdef0 --trace-id ab12cd34ef
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Iterator

from src import settings


def _ts(t: float) -> str:
    return dt.datetime.fromtimestamp(t).strftime("%H:%M:%S.%f")[:-3]


def _resolve_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    candidate = settings.LOG_DIR / f"session_{arg}.jsonl"
    if candidate.exists():
        return candidate
    candidate2 = settings.LOG_DIR / arg
    if candidate2.exists():
        return candidate2
    raise FileNotFoundError(arg)


def _latest() -> Path:
    files = sorted(settings.LOG_DIR.glob("session_*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"no session logs in {settings.LOG_DIR}")
    return files[-1]


def _read(path: Path) -> Iterator[dict]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _format_event(rec: dict) -> str:
    event = rec.get("event", "?")
    trace = rec.get("trace_id", "")
    node = rec.get("node", "")
    latency = rec.get("latency_ms")
    extras = {k: v for k, v in rec.items() if k not in {"ts", "session_id", "event", "trace_id", "node", "latency_ms"}}
    head = f"{_ts(rec['ts'])}  trace={trace[:8]:<8}  {event:<22}"
    if node:
        head += f"  node={node:<14}"
    if latency is not None:
        head += f"  {latency:>8} ms"
    extra_str = ""
    if extras:
        extra_str = " ".join(
            f"{k}={_short(v)}" for k, v in extras.items()
        )
    return f"{head}  {extra_str}".rstrip()


def _short(v) -> str:
    s = json.dumps(v, default=str)
    return s if len(s) <= 80 else s[:77] + "..."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", help="session_id, filename, or path")
    parser.add_argument("--latest", action="store_true", help="replay the most recent session")
    parser.add_argument("--trace-id", help="filter to a single trace_id")
    args = parser.parse_args()

    if args.latest or not args.target:
        path = _latest()
    else:
        path = _resolve_path(args.target)

    print(f"Replaying {path}")
    if args.trace_id:
        print(f"  filter: trace_id startswith {args.trace_id!r}")
    print("-" * 100)

    grouped: dict[str, list[dict]] = {}
    no_trace: list[dict] = []
    for rec in _read(path):
        if args.trace_id and not (rec.get("trace_id") or "").startswith(args.trace_id):
            continue
        tid = rec.get("trace_id")
        if tid:
            grouped.setdefault(tid, []).append(rec)
        else:
            no_trace.append(rec)

    for rec in no_trace:
        print(_format_event(rec))

    for tid, events in grouped.items():
        total_ms = sum(float(e.get("latency_ms") or 0) for e in events if e.get("event") == "node_end")
        print(f"\n=== trace {tid}  ({len(events)} events, {total_ms:.0f} ms) ===")
        for e in events:
            print("  " + _format_event(e))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
