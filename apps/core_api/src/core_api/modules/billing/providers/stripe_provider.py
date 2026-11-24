import logging
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import stripe

from core_api.infrastructure.settings import settings
from core_api.modules.billing.providers.protocol import (
    BillingProviderError,
    CheckoutConflictError,
    InvalidWebhookSignatureError,
    ProviderCustomer,
    ProviderBusinessIdentity,
    ProviderSession,
    ProviderSubscriptionChange,
    ProviderTaxId,
)


logger = logging.getLogger(__name__)


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
            email=email, name=name, metadata=dict(metadata),
            idempotency_key=f"rubrica-customer-{metadata['tenant_id']}" if "tenant_id" in metadata else None,
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
        parameters: dict[str, object] = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": tenant_id,
            "subscription_data": {
                "metadata": {"tenant_id": tenant_id, "product_code": product_code}
            },
            "metadata": {"tenant_id": tenant_id, "product_code": product_code, "price_id": price_id},
        }
        if product_code in {"rubrica_intermediate", "rubrica_team"}:
            parameters["tax_id_collection"] = {"enabled": True}
            parameters["customer_update"] = {"name": "auto", "address": "auto"}
        try:
            reusable, latest_id = self._reconcile_checkout(customer_id, tenant_id, price_id)
            if reusable:
                return ProviderSession(url=reusable)
            key = sha256(f"{tenant_id}:{customer_id}:{price_id}:{latest_id}".encode()).hexdigest()
            checkout = stripe.checkout.Session.create(**parameters, idempotency_key=f"rubrica-checkout-{key}")
        except CheckoutConflictError:
            raise
        except stripe.CardError as exc:
            raise CheckoutConflictError("The payment method was declined") from exc
        except Exception as exc:
            logger.warning(
                "Stripe checkout failed category=%s status=%s request_id=%s",
                type(exc).__name__, getattr(exc, "http_status", None), getattr(exc, "request_id", None),
            )
            raise BillingProviderError(
                "Stripe checkout could not be opened"
            ) from exc
        if not checkout.url:
            raise BillingProviderError("Stripe did not return a checkout URL")
        return ProviderSession(url=str(checkout.url))

    @staticmethod
    def _reconcile_checkout(customer_id: str, tenant_id: str, price_id: str) -> tuple[str | None, str]:
        latest_id = ""
        reusable = None
        obsolete = []
        for session in stripe.checkout.Session.list(customer=customer_id).auto_paging_iter():
            if session.get("client_reference_id") != tenant_id or session.get("mode") != "subscription":
                continue
            latest_id = latest_id or session.id
            if session.get("status") == "complete":
                if session.get("subscription"):
                    subscription = stripe.Subscription.retrieve(session["subscription"])
                    if subscription.get("status") not in {"canceled", "incomplete_expired"}:
                        raise CheckoutConflictError("An existing subscription must be resolved before starting another checkout")
                elif session.get("payment_status") == "paid" or session.get("invoice"):
                    raise CheckoutConflictError("A checkout payment is already in progress")
            if session.get("status") != "open":
                continue
            if session.get("payment_status") != "unpaid" or session.get("invoice") or session.get("subscription"):
                raise CheckoutConflictError("A checkout payment is already in progress")
            items = stripe.checkout.Session.list_line_items(session.id, limit=2).get("data", [])
            matches = len(items) == 1 and items[0].get("quantity") == 1 and (
                items[0].get("price") or {}
            ).get("id") == price_id
            if matches and session.get("url") and reusable is None:
                reusable = session["url"]
            else:
                obsolete.append(session.id)
        for session_id in obsolete:
            try:
                stripe.checkout.Session.expire(session_id)
            except stripe.InvalidRequestError as exc:
                raise CheckoutConflictError("Checkout changed while processing. Reload billing and try again") from exc
        return reusable, latest_id

    def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
        subscription_id: str | None = None,
        completion_url: str | None = None,
        price_id: str | None = None,
    ) -> ProviderSession:
        parameters: dict[str, object] = {
            "customer": customer_id,
            "return_url": return_url,
        }
        if settings.STRIPE_PORTAL_CONFIGURATION_ID:
            parameters["configuration"] = settings.STRIPE_PORTAL_CONFIGURATION_ID
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
            items = subscription.get("items", {}).get("data", [])
            if price_id and not items:
                raise BillingProviderError("Stripe subscription has no changeable item")
            flow_type = "subscription_update_confirm" if price_id else "subscription_update"
            flow_payload = (
                {"subscription": subscription_id, "items": [{"id": str(items[0].get("id")), "price": price_id, "quantity": 1}]}
                if price_id else {"subscription": subscription_id}
            )
            parameters["flow_data"] = {
                "type": flow_type,
                flow_type: flow_payload,
                "after_completion": {
                    "type": "redirect",
                    "redirect": {"return_url": completion_url or return_url},
                },
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

    def retrieve_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        try:
            return stripe.Subscription.retrieve(subscription_id)
        except Exception as exc:
            raise BillingProviderError(
                "Stripe subscription could not be synchronized"
            ) from exc

    def update_subscription_seats(
        self,
        *,
        subscription_id: str,
        product_code: str,
        base_price_id: str,
        seat_price_id: str,
        seat_price_ids: frozenset[str],
        additional_seats: int,
    ) -> ProviderSubscriptionChange:
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            existing_items = list(
                (subscription.get("items") or {}).get("data") or []
            )
            base_item = next(
                (
                    item
                    for item in existing_items
                    if str((item.get("price") or {}).get("id") or "")
                    not in seat_price_ids
                ),
                None,
            )
            if base_item is None:
                raise BillingProviderError(
                    "Stripe subscription has no base plan item"
                )
            seat_item = next(
                (
                    item
                    for item in existing_items
                    if str((item.get("price") or {}).get("id") or "")
                    in seat_price_ids
                ),
                None,
            )
            items: list[dict[str, object]] = [
                {
                    "id": str(base_item.get("id")),
                    "price": base_price_id,
                    "quantity": 1,
                }
            ]
            if additional_seats > 0:
                seat_change: dict[str, object] = {
                    "price": seat_price_id,
                    "quantity": additional_seats,
                }
                if seat_item is not None:
                    seat_change["id"] = str(seat_item.get("id"))
                items.append(seat_change)
            elif seat_item is not None:
                items.append(
                    {"id": str(seat_item.get("id")), "deleted": True}
                )
            updated = stripe.Subscription.modify(
                subscription_id,
                items=items,
                payment_behavior="pending_if_incomplete",
                proration_behavior="always_invoice",
                metadata={
                    **dict(subscription.get("metadata") or {}),
                    "product_code": product_code,
                },
                expand=["latest_invoice"],
            )
        except BillingProviderError:
            raise
        except Exception as exc:
            raise BillingProviderError(
                "Stripe could not update the contracted seats"
            ) from exc
        invoice = updated.get("latest_invoice")
        invoice_id = (
            str(invoice.get("id"))
            if isinstance(invoice, dict)
            else str(invoice or "")
        )
        if not invoice_id:
            raise BillingProviderError(
                "Stripe did not return the proration invoice"
            )
        return ProviderSubscriptionChange(invoice_id=invoice_id)

    def retrieve_customer_business_identity(
        self, customer_id: str
    ) -> ProviderBusinessIdentity:
        try:
            customer = stripe.Customer.retrieve(customer_id)
            tax_ids = stripe.Customer.list_tax_ids(customer_id, limit=100)
        except Exception as exc:
            raise BillingProviderError(
                "Stripe customer business identity could not be retrieved"
            ) from exc
        return ProviderBusinessIdentity(
            name=str(customer.get("name") or "").strip() or None,
            tax_ids=tuple(
                ProviderTaxId(
                    id=str(item.get("id") or ""),
                    type=str(item.get("type") or ""),
                    value=str(item.get("value") or ""),
                )
                for item in tax_ids.get("data", [])
            ),
        )

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
