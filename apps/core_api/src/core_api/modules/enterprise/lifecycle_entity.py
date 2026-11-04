from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from core_api.infrastructure.database.connection import BaseEntity


class EnterpriseLifecycle(BaseEntity):
    __tablename__ = "enterprise_lifecycle"
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class EnterpriseNotice(BaseEntity):
    __tablename__ = "enterprise_notices"
    __table_args__ = (UniqueConstraint("tenant_id", "kind", "reference", name="uq_enterprise_notice"),)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    reference: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    delivered_to: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    email_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EnterprisePurgeCopy(BaseEntity):
    __tablename__ = "enterprise_purge_copies"
    __table_args__ = (UniqueConstraint("source_kind", "source_id", "storage_key", name="uq_enterprise_purge_copy"),)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    integration_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_integrations.id", ondelete="RESTRICT"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    namespace: Mapped[str] = mapped_column(String(24), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    counted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))


class EnterpriseWebhook(BaseEntity):
    __tablename__ = "enterprise_webhooks"
    integration_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_integrations.id", ondelete="RESTRICT"), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    secret_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class EnterpriseWebhookDelivery(BaseEntity):
    __tablename__ = "enterprise_webhook_deliveries"
    __table_args__ = (UniqueConstraint("endpoint_id", "event_id", name="uq_enterprise_webhook_event"),)
    endpoint_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_webhooks.id", ondelete="RESTRICT"), nullable=False)
    event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retry_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
