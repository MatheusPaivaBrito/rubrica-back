from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, Integer, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from observability_api.infrastructure.database.connection import Base


class EnterpriseUsageRecord(Base):
    __tablename__ = "enterprise_usage_records"
    __table_args__ = (Index("ix_enterprise_projection_tenant_window", "tenant_id", "integration_id", "sandbox", "occurred_at"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    integration_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    compartment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    token_public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
