from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from core_api.infrastructure.database.connection import BaseEntity


class EnterpriseOperation(BaseEntity):
    __tablename__ = "enterprise_operations"
    __table_args__ = (UniqueConstraint("request_id", "signer_id", name="uq_enterprise_provider_operation"),)
    request_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_requests.id", ondelete="RESTRICT"), nullable=False)
    signer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    signature_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    command_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_checkpoint: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))


class EnterpriseJob(BaseEntity):
    __tablename__ = "enterprise_jobs"
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    integration_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    compartment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    signing_session_id: Mapped[UUID | None] = mapped_column(Uuid)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    encrypted_payload: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(80))
    owner: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EnterpriseExecutionSlot(BaseEntity):
    __tablename__ = "enterprise_execution_slots"
    __table_args__ = (UniqueConstraint("environment", "sandbox", "number", name="uq_enterprise_execution_slot"),)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    job_id: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnterpriseAdministrationBudget(BaseEntity):
    __tablename__ = "enterprise_administration_budgets"
    identity: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    minute: Mapped[int] = mapped_column(Integer, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
