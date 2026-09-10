from typing import Any, Mapping

import stripe

from core_api.infrastructure.settings import settings
from core_api.modules.billing.providers.protocol import (
    BillingProviderError,
    InvalidWebhookSignatureError,
    ProviderCustomer,
    ProviderSession,
)


class StripeBillingProvider:
    def __init__(self) -> None:
        if not settings.STRIPE_SECRET_KEY:
            raise BillingProviderError("Stripe is not configured")
        stripe.api_key = settings.STRIPE_SECRET_KEY

    def create_customer(
        self,
        *,
        email: str,
        name: str,
        metadata: Mapping[str, str],
    ) -> ProviderCustomer:
        customer = stripe.Customer.create(
            email=email, name=name, metadata=dict(metadata)
        )
        return ProviderCustomer(id=str(customer.id))

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        tenant_id: str,
        success_url: str,
        cancel_url: str,
    ) -> ProviderSession:
        checkout = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=tenant_id,
            subscription_data={
                "metadata": {"tenant_id": tenant_id, "product_code": "rubrica_mvp"}
            },
            metadata={"tenant_id": tenant_id},
        )
        if not checkout.url:
            raise BillingProviderError("Stripe did not return a checkout URL")
        return ProviderSession(url=str(checkout.url))

    def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> ProviderSession:
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        if not portal.url:
            raise BillingProviderError("Stripe did not return a portal URL")
        return ProviderSession(url=str(portal.url))

    def construct_webhook_event(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> Mapping[str, Any]:
        if not settings.STRIPE_WEBHOOK_SECRET:
            raise BillingProviderError("Stripe webhook is not configured")
        try:
            return stripe.Webhook.construct_event(
                payload,
                signature,
                settings.STRIPE_WEBHOOK_SECRET,
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise InvalidWebhookSignatureError from exc
