from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared_kernel.identifiers import Identifier


class BillingPlanRead(BaseModel):
    id: Identifier
    code: str
    name: str
    price_cents: int
    currency: str
    billing_interval: str

    model_config = ConfigDict(from_attributes=True)


class CheckoutCreate(BaseModel):
    plan_id: Identifier
    payer_email: str = Field(min_length=3, max_length=320)
    payment_method: Literal["card", "pix"] | None = None

    @field_validator("payer_email")
    @classmethod
    def validate_payer_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("payer_email must be a valid email address")
        return email


class PublicCheckoutCreate(BaseModel):
    plan_id: Identifier
    company_name: str = Field(min_length=2, max_length=160)
    legal_name: str = Field(min_length=2, max_length=160)
    document: str = Field(min_length=11, max_length=32)
    admin_name: str = Field(min_length=2, max_length=120)
    payer_email: str = Field(min_length=3, max_length=320)
    phone: str = Field(min_length=8, max_length=32)

    @field_validator("payer_email")
    @classmethod
    def validate_payer_email(cls, value: str) -> str:
        return CheckoutCreate.validate_payer_email(value)

    @field_validator("document")
    @classmethod
    def normalize_document(cls, value: str) -> str:
        digits = "".join(character for character in value if character.isdigit())
        if len(digits) not in {11, 14}:
            raise ValueError("document must be a valid CPF or CNPJ")
        return digits


class CheckoutRead(BaseModel):
    id: Identifier
    status: str
    checkout_url: str | None
    provider: str
    subscription_id: Identifier | None
    provisioning_status: str = "not_required"
    expires_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class BillingSubscriptionRead(BaseModel):
    id: Identifier
    plan_id: Identifier | None
    provider: str
    status: str
    current_period_end: datetime | None

    model_config = ConfigDict(from_attributes=True)


class MercadoPagoWebhookPayload(BaseModel):
    id: int | str | None = None
    type: str = Field(min_length=1, max_length=80)
    action: str | None = Field(default=None, max_length=120)
    data: dict[str, str | int]


class WebhookRead(BaseModel):
    received: bool = True
    duplicate: bool = False


class BillingPaymentRead(BaseModel):
    id: Identifier
    status: str
    amount_cents: int
    currency: str
    paid_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublicCheckoutStatusRead(BaseModel):
    id: Identifier
    status: str
    provisioning_status: str
