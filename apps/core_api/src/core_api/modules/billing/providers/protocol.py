from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class BillingProviderError(Exception):
    pass


class InvalidWebhookSignatureError(BillingProviderError):
    pass


@dataclass(frozen=True)
class ProviderCustomer:
    id: str


@dataclass(frozen=True)
class ProviderSession:
    url: str


class BillingProvider(Protocol):
    def create_customer(
        self,
        *,
        email: str,
        name: str,
        metadata: Mapping[str, str],
    ) -> ProviderCustomer: ...

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        product_code: str,
        tenant_id: str,
        success_url: str,
        cancel_url: str,
    ) -> ProviderSession: ...

    def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
        subscription_id: str | None = None,
        completion_url: str | None = None,
    ) -> ProviderSession: ...

    def retrieve_subscription(self, subscription_id: str) -> Mapping[str, Any]: ...

    def construct_webhook_event(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> Mapping[str, Any]: ...
