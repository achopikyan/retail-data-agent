"""Per-user preferences (whitelisted keys)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.identity import Identity, get_identity
from src.api.schemas import PrefsOut, SetPrefRequest
from src.tools import prefs_store

router = APIRouter(prefix="/api/prefs", tags=["prefs"])


@router.get("", response_model=PrefsOut)
def get_prefs(identity: Identity = Depends(get_identity)) -> PrefsOut:
    return PrefsOut(
        user_id=identity.user_id,
        prefs=prefs_store.get_prefs(identity.user_id),
    )


@router.put("", response_model=PrefsOut)
def set_pref(
    req: SetPrefRequest, identity: Identity = Depends(get_identity)
) -> PrefsOut:
    try:
        prefs_store.set_pref(identity.user_id, req.key, req.value)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return PrefsOut(
        user_id=identity.user_id,
        prefs=prefs_store.get_prefs(identity.user_id),
    )


@router.get("/allowed-keys", response_model=list[str])
def allowed_keys() -> list[str]:
    return sorted(prefs_store.ALLOWED_KEYS)
