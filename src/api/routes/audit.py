"""Read-only audit log."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Query

from src.api.schemas import AuditEntry
from src.tools import reports_store

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=List[AuditEntry])
def list_audit(limit: int = Query(default=50, ge=1, le=500)) -> List[AuditEntry]:
    rows = reports_store.audit_recent(limit=limit)
    return [
        AuditEntry(
            id=r["id"],
            ts=r["ts"],
            actor_id=r["actor_id"],
            action=r["action"],
            target_ids=r["target_ids"],
            reason=r["reason"],
            trace_id=r["trace_id"],
        )
        for r in rows
    ]
