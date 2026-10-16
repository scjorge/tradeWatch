from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import User


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool
    roles: list[str]
    permissions: list[str]
    timezone: str
    base_currency: str
    cost_method: str
    mfa_enabled: bool
    created_at: datetime


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
        roles=user.role_keys,
        permissions=sorted(user.permission_keys),
        timezone=user.timezone,
        base_currency=user.base_currency,
        cost_method=user.cost_method,
        mfa_enabled=user.mfa_enabled,
        created_at=user.created_at,
    )
