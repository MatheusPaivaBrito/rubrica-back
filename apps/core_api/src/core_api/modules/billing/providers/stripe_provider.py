from pathlib import Path
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
        product_code: str,
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
                "metadata": {"tenant_id": tenant_id, "product_code": product_code}
            },
            metadata={"tenant_id": tenant_id, "product_code": product_code},
        )
        if not checkout.url:
            raise BillingProviderError("Stripe did not return a checkout URL")
        return ProviderSession(url=str(checkout.url))

    def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
        subscription_id: str | None = None,
    ) -> ProviderSession:
        parameters: dict[str, object] = {
            "customer": customer_id,
            "return_url": return_url,
        }
        cancellation_was_scheduled = False
        if subscription_id:
            subscription = stripe.Subscription.retrieve(subscription_id)
            cancellation_was_scheduled = bool(
                subscription.get("cancel_at_period_end", False)
            )
            if cancellation_was_scheduled:
                stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=False,
                )
            parameters["flow_data"] = {
                "type": "subscription_update",
                "subscription_update": {"subscription": subscription_id},
                "after_completion": {"type": "portal_homepage"},
            }
        try:
            portal = stripe.billing_portal.Session.create(**parameters)
        except Exception as exc:
            if subscription_id and cancellation_was_scheduled:
                stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True,
                )
            raise BillingProviderError(
                "Stripe billing portal could not be opened"
            ) from exc
        if not portal.url:
            raise BillingProviderError("Stripe did not return a portal URL")
        return ProviderSession(url=str(portal.url))

    def construct_webhook_event(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> Mapping[str, Any]:
        webhook_secret = self._webhook_secret()
        if not webhook_secret:
            raise BillingProviderError("Stripe webhook is not configured")
        try:
            return stripe.Webhook.construct_event(
                payload,
                signature,
                webhook_secret,
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise InvalidWebhookSignatureError from exc

    @staticmethod
    def _webhook_secret() -> str | None:
        runtime_path = settings.STRIPE_RUNTIME_WEBHOOK_SECRET_FILE
        if runtime_path:
            try:
                runtime_secret = Path(runtime_path).read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                runtime_secret = ""
            except OSError as exc:
                raise BillingProviderError(
                    "Stripe runtime webhook secret could not be read"
                ) from exc
            if runtime_secret:
                return runtime_secret
        return settings.STRIPE_WEBHOOK_SECRET
