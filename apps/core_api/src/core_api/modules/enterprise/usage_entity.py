from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column

from core_api.infrastructure.database.connection import BaseEntity


class EnterpriseUsageEvent(BaseEntity):
    __tablename__ = "enterprise_usage_events"
    __table_args__ = (UniqueConstraint("kind", "source_id", name="uq_enterprise_usage_source"),)
    source_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    integration_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    compartment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    token_public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    price_version: Mapped[str] = mapped_column(String(40), nullable=False, default="enterprise-zero-v1")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float | None] = mapped_column(Float)


class EnterpriseTelemetryOutbox(BaseEntity):
    __tablename__ = "enterprise_telemetry_outbox"
    event_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_usage_events.id", ondelete="RESTRICT"), nullable=False, unique=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class EnterpriseQuota(BaseEntity):
    __tablename__ = "enterprise_quotas"
    __table_args__ = (UniqueConstraint("tenant_id", "sandbox", name="uq_enterprise_quota_mode"),)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    storage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signing_day: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    signing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EnterpriseApiRateBucket(BaseEntity):
    __tablename__ = "enterprise_api_rate_buckets"
    __table_args__ = (UniqueConstraint("tenant_id", "sandbox", name="uq_enterprise_rate_mode"),)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    minute: Mapped[int] = mapped_column(BigInteger, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)


@event.listens_for(EnterpriseUsageEvent, "before_update")
@event.listens_for(EnterpriseUsageEvent, "before_delete")
def immutable_fact(*_):
    raise ValueError("Usage ledger facts are immutable; corrections require a separate event")
