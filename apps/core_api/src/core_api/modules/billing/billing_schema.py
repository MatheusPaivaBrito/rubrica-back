from datetime import datetime
from uuid import UUID

from typing import Literal

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
    plan_code: str
    contracted_seats: int
    pending_product_code: str | None
    pending_contracted_seats: int | None
    pending_change_kind: str | None
    pending_change_effective_at: datetime | None
    entitlements: list[str]
    current_period_ends_at: datetime | None
    cancel_at_period_end: bool
    cancels_at: datetime | None
    grace_period_ends_at: datetime | None
    free_signatures_limit: int
    signatures_used: int
    signatures_remaining: int | None
    unlimited_signatures: bool
    files_uploaded_in_period: int
    files_limit: int | None
    files_remaining: int | None
    unlimited_files: bool
    email_invitations_enabled: bool
    custom_stamp_placement: bool
    custom_stamp_branding: bool
    trusted_timestamp: bool
    serproid_signature: bool
    team_management: bool
    usage_period_starts_at: datetime | None
    complimentary_lifetime: bool
    created_at: datetime


class BillingCheckoutRead(BaseModel):
    checkout_url: str


class BillingCheckoutCreate(BaseModel):
    product_code: Literal["rubrica_base", "rubrica_intermediate", "rubrica_team"]
    billing_interval: Literal["month", "year"] = "month"


class BillingPortalRead(BaseModel):
    portal_url: str


class BillingPlanChangeCreate(BillingCheckoutCreate):
    pass


class BillingSeatQuoteCreate(BaseModel):
    target_seats: int
    billing_interval: Literal["month", "year"] = "month"


class BillingSeatQuoteRead(BaseModel):
    target_product_code: Literal["rubrica_intermediate", "rubrica_team"]
    target_seats: int
    documents_limit: int
    recurring_amount_minor: int
    currency: str
    billing_interval: Literal["month", "year"]
    effective: Literal["immediate", "next_renewal"]
    effective_at: datetime | None


class BillingSeatChangeCreate(BillingSeatQuoteCreate):
    pass


class BillingSeatChangeRead(BaseModel):
    status: Literal["pending_payment", "scheduled"]
    target_product_code: Literal["rubrica_intermediate", "rubrica_team"]
    target_seats: int
    effective_at: datetime | None


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
