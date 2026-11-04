from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from core_api.infrastructure.database.connection import BaseEntity


class EnterpriseClosure(BaseEntity):
    __tablename__ = "enterprise_closures"
    __table_args__ = (UniqueConstraint("tenant_id", "revision", name="uq_enterprise_closure_revision"),)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    objects_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credentials_retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backups_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backup_receipt: Mapped[dict | None] = mapped_column(JSON)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
