import json
from typing import Any, Mapping
from uuid import uuid4

from core_api.modules.billing.providers.protocol import ProviderCustomer, ProviderSession


class FakeBillingProvider:
    """Local provider for exercising billing screens without external charges."""

    def create_customer(
        self,
        *,
        email: str,
        name: str,
        metadata: Mapping[str, str],
    ) -> ProviderCustomer:
        return ProviderCustomer(id=f"fake_customer_{uuid4()}")

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        tenant_id: str,
        success_url: str,
        cancel_url: str,
    ) -> ProviderSession:
        return ProviderSession(url=success_url)

    def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> ProviderSession:
        return ProviderSession(url=return_url)

    def construct_webhook_event(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> Mapping[str, Any]:
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError("Fake billing event must be a JSON object")
        return value
