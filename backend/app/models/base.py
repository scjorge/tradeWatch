from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

# Valores financeiros: decimal com 38 dígitos, 18 casas (cobre satoshis e tokens com 18 decimais).
Amount = Numeric(38, 18)


def utcnow() -> datetime:
    return datetime.now(UTC)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def tz_datetime(nullable: bool = True, **kw) -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True), nullable=nullable, **kw)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow, server_default=func.now()
    )


__all__ = ["Amount", "Decimal", "TimestampMixin", "utcnow", "uuid_pk", "tz_datetime"]
