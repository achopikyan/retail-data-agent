"""Header-based identity extraction.

The web app sets `X-User-Id` and `X-User-Role` on every request — mirrors
the CLI's /login model. There's no real authentication; production would
slot OAuth/JWT in here without changing call sites.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Header

from src import settings
from src.tools.reports_store import GDPR_ROLE


_ALLOWED_ROLES = {"manager", GDPR_ROLE}


@dataclass(frozen=True)
class Identity:
    user_id: str
    role: str


def get_identity(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
) -> Identity:
    user_id = (x_user_id or settings.DEFAULT_USER_ID).strip() or settings.DEFAULT_USER_ID
    role = (x_user_role or "manager").strip() or "manager"
    if role not in _ALLOWED_ROLES:
        role = "manager"
    return Identity(user_id=user_id, role=role)
