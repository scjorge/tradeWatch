from __future__ import annotations

import logging
import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.redaction import redact_obj
from app.models import AuditLog

log = logging.getLogger("app.audit")


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def audit(
    db: Session,
    action: str,
    *,
    user_id: uuid.UUID | None = None,
    request: Request | None = None,
    target_type: str | None = None,
    target_id: object | None = None,
    **details,
) -> None:
    """Registra um evento de segurança/configuração. O commit é responsabilidade do chamador."""
    safe = redact_obj(details)
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent", "")[:300] if request else None),
            details=safe,
        )
    )
    log.info("audit", extra={"action": action, "user_id": str(user_id) if user_id else None, **safe})
