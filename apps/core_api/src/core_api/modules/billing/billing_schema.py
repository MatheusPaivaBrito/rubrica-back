from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BillingAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    status: str
    provider: str | None
    provider_customer_id: str | None
    provider_subscription_id: str | None
    current_product_code: str | None
    current_period_ends_at: datetime | None
    grace_period_ends_at: datetime | None
    free_signatures_limit: int
    signatures_used: int
    signatures_remaining: int | None
    unlimited_signatures: bool
    created_at: datetime


class BillingCheckoutRead(BaseModel):
    checkout_url: str


class BillingPortalRead(BaseModel):
    portal_url: str


class BillingWebhookRead(BaseModel):
    accepted: bool = True
    duplicate: bool = False


class BillingPaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    provider: str
    provider_payment_id: str
    provider_subscription_id: str | None
    status: str
    currency: str
    amount_due_minor: int
    amount_paid_minor: int
    period_starts_at: datetime | None
    period_ends_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime
