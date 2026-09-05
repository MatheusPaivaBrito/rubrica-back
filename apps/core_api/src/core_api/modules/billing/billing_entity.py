from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from core_api.infrastructure.database.connection import BaseEntity
from shared_kernel.identifiers import Identifier


class BillingCheckoutSessionEntity(BaseEntity):
    __tablename__ = "billing_checkout_sessions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_billing_checkout_tenant_key"
        ),
    )

    tenant_id: Mapped[Identifier | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    plan_id: Mapped[Identifier] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subscription_id: Mapped[Identifier | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_checkout_id: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payer_email: Mapped[str] = mapped_column(String(320), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    legal_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    document: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    admin_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provisioning_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_required", index=True
    )
    auth_user_id: Mapped[Identifier | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BillingPaymentEntity(BaseEntity):
    __tablename__ = "billing_payments"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_payment_id", name="uq_billing_payment_provider_id"
        ),
    )

    tenant_id: Mapped[Identifier] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subscription_id: Mapped[Identifier] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_payment_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BillingEventEntity(BaseEntity):
    __tablename__ = "billing_events"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_event_id", name="uq_billing_event_provider_id"
        ),
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(240), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    action: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resource_id: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
