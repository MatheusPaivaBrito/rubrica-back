from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CheckoutRequest:
    reason: str
    external_reference: str
    payer_email: str
    amount_cents: int
    currency: str
    interval: str
    back_url: str
    notification_url: str
    idempotency_key: str


@dataclass(frozen=True)
class CheckoutResult:
    provider_id: str
    checkout_url: str
    status: str


class BillingProvider(Protocol):
    name: str

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult: ...

    def get_payment(self, resource_id: str) -> dict: ...

    def get_subscription(self, resource_id: str) -> dict: ...

    def cancel_subscription(self, resource_id: str) -> dict: ...
