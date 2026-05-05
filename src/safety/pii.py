"""PII masking: column-level + cell-level + final-text scrub.

Strategy
--------
1. Column-level: any column whose name matches the SENSITIVE_COL pattern
   has its values replaced with a deterministic short hash. Originals are
   never returned.
2. Cell-level: every string cell in every column is scanned for email and
   phone patterns, replacing matches with the same deterministic hash.
3. Text-level: a final pass on synthesized report text catches anything
   that survived (e.g. PII embedded inside a string aggregation that the
   model copied into the report).

The hash makes the same person resolve to the same opaque token across
columns and rows, so the model can still reason about identity without
seeing actual contact details.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


SENSITIVE_COL = re.compile(
    r"(?i)\b(email|e_mail|phone|mobile|tel|telephone|first_name|last_name|full_name|address|street|zip|postal)\b"
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Catches:
#   +972-50-123-4567, 0501234567, 050-123-4567, (555) 123-4567,
#   +1 555 123 4567, etc. Tuned for plausibility rather than exhaustiveness.
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,4}\)?[\s\-.]?)?\d{3}[\s\-.]?\d{3,4}(?!\w)"
)


def _hash_token(value: str, prefix: str = "cust") -> str:
    digest = hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{digest}"


@dataclass
class MaskResult:
    df: pd.DataFrame
    hash_map: Dict[str, str] = field(default_factory=dict)
    masked_columns: List[str] = field(default_factory=list)
    cell_hits: int = 0


def _mask_value(value: str, hash_map: Dict[str, str]) -> Tuple[str, int]:
    """Mask emails and phones inside a string. Returns (new_value, hit_count)."""
    hits = 0

    def _email_sub(m: re.Match) -> str:
        nonlocal hits
        hits += 1
        token = _hash_token(m.group(0))
        hash_map[m.group(0)] = token
        return token

    def _phone_sub(m: re.Match) -> str:
        nonlocal hits
        raw = m.group(0)
        # Skip ambiguous short numerics that look like IDs/years/quantities.
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 9:
            return raw
        hits += 1
        token = _hash_token(raw)
        hash_map[raw] = token
        return token

    new_value = EMAIL_RE.sub(_email_sub, value)
    new_value = PHONE_RE.sub(_phone_sub, new_value)
    return new_value, hits


def mask_dataframe(df: pd.DataFrame) -> MaskResult:
    """Mask PII in a DataFrame. Returns a copy plus mask metadata."""
    if df is None or df.empty:
        return MaskResult(df=df if df is not None else pd.DataFrame())

    out = df.copy()
    hash_map: Dict[str, str] = {}
    masked_cols: List[str] = []
    cell_hits = 0

    # 1. Column-level mask for known sensitive column names.
    for col in out.columns:
        if SENSITIVE_COL.search(str(col)):
            masked_cols.append(col)
            out[col] = out[col].astype("object").map(
                lambda v: _hash_token(str(v)) if pd.notna(v) else v
            )

    # 2. Cell-level mask for any remaining string-bearing columns.
    # Pandas 3.x defaults to `string[python]` dtype rather than `object`,
    # so we accept either — plus we let the inner `isinstance(v, str)`
    # check filter non-string values for safety.
    for col in out.columns:
        if col in masked_cols:
            continue
        col_dtype = out[col].dtype
        is_object = col_dtype == object
        is_string = pd.api.types.is_string_dtype(out[col])
        if not (is_object or is_string):
            continue
        new_col = []
        for v in out[col]:
            if not isinstance(v, str):
                new_col.append(v)
                continue
            masked, hits = _mask_value(v, hash_map)
            cell_hits += hits
            new_col.append(masked)
        out[col] = new_col

    return MaskResult(df=out, hash_map=hash_map, masked_columns=masked_cols, cell_hits=cell_hits)


def scrub_text(text: str) -> Tuple[str, int]:
    """Final-pass scrub on report text. Returns (clean_text, leakage_hits)."""
    if not text:
        return text, 0
    hash_map: Dict[str, str] = {}
    cleaned, hits = _mask_value(text, hash_map)
    if hits:
        logger.warning("PII leakage caught in report-text scrub: %d hits", hits)
    return cleaned, hits
