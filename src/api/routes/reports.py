"""Saved reports CRUD + destructive-op confirmation."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.identity import Identity, get_identity
from src.api.schemas import (
    DeleteMatchingRequest,
    DeleteResponse,
    ReportOut,
    SaveReportRequest,
)
from src.tools import reports_store
from src.tools.reports_store import GDPR_ROLE

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _to_out(r: reports_store.Report) -> ReportOut:
    return ReportOut(
        id=r.id,
        owner_id=r.owner_id,
        title=r.title,
        body=r.body,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


@router.get("", response_model=List[ReportOut])
def list_reports(
    show_all: bool = Query(default=False, alias="all"),
    identity: Identity = Depends(get_identity),
) -> List[ReportOut]:
    if show_all and identity.role != GDPR_ROLE:
        raise HTTPException(403, f"'all=true' requires the {GDPR_ROLE} role")
    owner = None if show_all else identity.user_id
    return [_to_out(r) for r in reports_store.list_for(owner)]


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: int) -> ReportOut:
    r = reports_store.get(report_id)
    if not r:
        raise HTTPException(404, f"no report with id {report_id}")
    return _to_out(r)


@router.post("", response_model=ReportOut, status_code=201)
def save_report(
    req: SaveReportRequest, identity: Identity = Depends(get_identity)
) -> ReportOut:
    rid = reports_store.save(identity.user_id, req.title, req.body)
    saved = reports_store.get(rid)
    assert saved is not None
    return _to_out(saved)


@router.delete("/{report_id}", response_model=DeleteResponse)
def delete_report(
    report_id: int,
    confirm: str = Query(..., description="must be 'yes' to actually delete"),
    reason: str = Query(default=""),
    identity: Identity = Depends(get_identity),
) -> DeleteResponse:
    if confirm.lower() not in {"yes", "y"}:
        raise HTTPException(400, "destructive op requires confirm=yes")
    if not reports_store.get(report_id):
        raise HTTPException(404, f"no report with id {report_id}")
    try:
        deleted = reports_store.delete_ids(
            [report_id],
            actor_id=identity.user_id,
            actor_role=identity.role,
            reason=reason,
            trace_id=None,
        )
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    return DeleteResponse(deleted=deleted, target_ids=[report_id])


@router.post("/delete-matching", response_model=DeleteResponse)
def delete_matching(
    req: DeleteMatchingRequest, identity: Identity = Depends(get_identity)
) -> DeleteResponse:
    """Delete all reports whose title or body contains `substring`.

    Same-user deletes (or gdpr_officer with no cross-user matches) are
    allowed with no extra check. Cross-user deletes (gdpr_officer
    operating on someone else's reports) require `expected_count` to
    match exactly — guards against fat-finger destructive ops.
    """
    owner_filter = None if identity.role == GDPR_ROLE else identity.user_id
    matched = reports_store.find_matching(req.substring, owner_id=owner_filter)
    if not matched:
        return DeleteResponse(deleted=0, target_ids=[])

    cross_user = any(m.owner_id != identity.user_id for m in matched)
    if cross_user:
        if identity.role != GDPR_ROLE:
            raise HTTPException(
                403, f"cross-user delete requires the {GDPR_ROLE} role"
            )
        if req.expected_count is None:
            raise HTTPException(
                400,
                f"cross-user delete requires 'expected_count' to equal the "
                f"matched count ({len(matched)}) for confirmation",
            )
        if req.expected_count != len(matched):
            raise HTTPException(
                400,
                f"expected_count mismatch — got {req.expected_count}, "
                f"matched {len(matched)}. Refresh and re-submit.",
            )

    target_ids = [m.id for m in matched]
    try:
        deleted = reports_store.delete_ids(
            target_ids,
            actor_id=identity.user_id,
            actor_role=identity.role,
            reason=req.reason,
            trace_id=None,
        )
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    return DeleteResponse(deleted=deleted, target_ids=target_ids)
