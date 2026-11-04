from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, JSON, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from auth_api.infrastructure.database.connection import BaseEntity


class MachineCredentialEntity(BaseEntity):
    __tablename__ = "machine_credentials"
    __table_args__ = (UniqueConstraint(
        "integration_id", "environment", "sandbox", name="uq_machine_integration_environment"
    ),)

    # References to Core resources are opaque IDs, never cross-database FKs.
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    integration_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    public_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    digest: Mapped[str | None] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_by: Mapped[str | None] = mapped_column(String(255))


class MachineCredentialAuditEntity(BaseEntity):
    __tablename__ = "machine_credential_audit"

    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    integration_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    public_id: Mapped[str | None] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
