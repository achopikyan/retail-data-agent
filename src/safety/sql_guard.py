"""Static SQL guardrails — last line of defense before BigQuery.

The DB connection is read-only at the GCP-IAM level in production, but
we still validate at the application layer to fail fast and to keep the
agent honest. Rules:

- Must be a SELECT or WITH...SELECT.
- No DDL / DML keywords.
- Only references the allowed dataset.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src import settings


_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|REPLACE|CALL|EXECUTE)\b",
    re.IGNORECASE,
)
_STATEMENT_TERMINATOR = re.compile(r";\s*\S")  # multiple statements


@dataclass
class GuardResult:
    ok: bool
    reason: str | None = None


def validate_sql(sql: str) -> GuardResult:
    if not sql or not sql.strip():
        return GuardResult(False, "empty SQL")

    # Strip leading/trailing semicolons & whitespace before lead-keyword check.
    cleaned = sql.strip().rstrip(";").strip()
    head = re.split(r"\s+", cleaned, maxsplit=1)[0].upper()
    if head not in {"SELECT", "WITH"}:
        return GuardResult(False, f"only SELECT/WITH queries are allowed (got {head})")

    if _FORBIDDEN.search(cleaned):
        return GuardResult(False, "forbidden keyword detected (DDL/DML not allowed)")

    if _STATEMENT_TERMINATOR.search(cleaned):
        return GuardResult(False, "multiple SQL statements not allowed")

    if settings.DATASET not in cleaned:
        return GuardResult(
            False,
            f"query must reference dataset `{settings.DATASET}`",
        )

    return GuardResult(True)
