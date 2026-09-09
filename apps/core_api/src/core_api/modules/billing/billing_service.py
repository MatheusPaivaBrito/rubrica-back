from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import stripe
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import BillingAccountEntity, BillingEventEntity
from core_api.modules.billing.billing_schema import (
    BillingAccountRead,
    BillingCheckoutRead,
    BillingPortalRead,
    BillingWebhookRead,
)
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import TenantEntity
from core_api.modules.tenant.tenant_service import tenant_service
from shared_kernel.time.datetime_service import DateTimeService


class BillingService:
    def account(self, tenant_id: UUID, subject: str) -> BillingAccountRead:
        return self._account(tenant_id, subject, {"admin", "auditor"})

    def initialize(self, tenant_id: UUID, subject: str) -> BillingAccountRead:
        return self._account(tenant_id, subject, {"admin"})

    def create_checkout(self, tenant_id: UUID, subject: str) -> BillingCheckoutRead:
        self._configure_stripe()
        with SessionLocal.begin() as database:
            tenant_service.require_role(database, tenant_id, subject, {"admin"})
            tenant = database.get(TenantEntity, tenant_id)
            if tenant is None or tenant.deleted_at is not None:
                raise WorkflowError("Tenant not found", 404)
            price_id = self._price_for_currency(tenant.currency)
            account = self._account_entity(database, tenant_id)
            if not account.provider_customer_id:
                customer = stripe.Customer.create(
                    email=subject,
                    name=tenant.name,
                    metadata={"tenant_id": str(tenant.id)},
                )
                account.provider = "stripe"
                account.provider_customer_id = customer.id
            checkout = stripe.checkout.Session.create(
                mode="subscription",
                customer=account.provider_customer_id,
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=f"{settings.PUBLIC_WEB_URL.rstrip('/')}/billing?checkout=success",
                cancel_url=f"{settings.PUBLIC_WEB_URL.rstrip('/')}/billing?checkout=cancelled",
                client_reference_id=str(tenant.id),
                subscription_data={
                    "metadata": {
                        "tenant_id": str(tenant.id),
                        "product_code": "rubrica_mvp",
                    }
                },
                metadata={"tenant_id": str(tenant.id)},
            )
            if not checkout.url:
                raise WorkflowError("Stripe did not return a checkout URL", 502)
            return BillingCheckoutRead(checkout_url=checkout.url)

    def create_portal(self, tenant_id: UUID, subject: str) -> BillingPortalRead:
        self._configure_stripe()
        with SessionLocal.begin() as database:
            tenant_service.require_role(database, tenant_id, subject, {"admin"})
            account = self._account_entity(database, tenant_id)
            if not account.provider_customer_id:
                raise WorkflowError("Stripe customer is not configured", 409)
            portal = stripe.billing_portal.Session.create(
                customer=account.provider_customer_id,
                return_url=f"{settings.PUBLIC_WEB_URL.rstrip('/')}/billing",
            )
            return BillingPortalRead(portal_url=portal.url)

    def receive_webhook(self, payload: bytes, signature: str) -> BillingWebhookRead:
        self._configure_stripe(require_webhook=True)
        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                settings.STRIPE_WEBHOOK_SECRET,
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise WorkflowError("Invalid Stripe webhook signature", 400) from exc

        event_id = str(event["id"])
        with SessionLocal() as database:
            duplicate = database.scalar(
                select(BillingEventEntity.id).where(
                    BillingEventEntity.provider == "stripe",
                    BillingEventEntity.provider_event_id == event_id,
                )
            )
        if duplicate is not None:
            return BillingWebhookRead(duplicate=True)

        event_type = str(event["type"])
        resource = event["data"]["object"]
        resource_id = str(resource.get("id", "unknown"))
        tenant_id = self._tenant_id(resource)
        sanitized = {
            "type": event_type,
            "resource_id": resource_id,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "customer_id": resource.get("customer"),
            "subscription_id": resource.get("subscription"),
            "status": resource.get("status"),
        }
        try:
            with SessionLocal.begin() as database:
                billing_event = BillingEventEntity(
                    tenant_id=tenant_id,
                    provider="stripe",
                    provider_event_id=event_id,
                    event_type=event_type,
                    resource_id=resource_id,
                    payload_hash=sha256(payload).hexdigest(),
                    payload_sanitized=sanitized,
                    status="received",
                )
                database.add(billing_event)
                self._apply_event(database, event_type, resource, tenant_id)
                billing_event.status = "processed"
                billing_event.processed_at = DateTimeService.utc_now()
        except IntegrityError:
            return BillingWebhookRead(duplicate=True)
        return BillingWebhookRead()

    @staticmethod
    def _apply_event(database, event_type: str, resource, tenant_id: UUID | None) -> None:
        if tenant_id is None:
            return
        account = BillingService._account_entity(database, tenant_id)
        account.provider = "stripe"
        customer = resource.get("customer")
        if customer:
            account.provider_customer_id = str(customer)
        if event_type == "checkout.session.completed":
            subscription = resource.get("subscription")
            account.provider_subscription_id = str(subscription) if subscription else None
            account.current_product_code = "rubrica_mvp"
            account.status = "active"
            return
        if event_type.startswith("customer.subscription."):
            account.provider_subscription_id = str(resource.get("id"))
            account.current_product_code = str(
                resource.get("metadata", {}).get("product_code", "rubrica_mvp")
            )
            account.status = BillingService._subscription_status(str(resource.get("status", "")))
            period_end = resource.get("current_period_end")
            account.current_period_ends_at = (
                datetime.fromtimestamp(int(period_end), tz=UTC) if period_end else None
            )

    @staticmethod
    def _subscription_status(provider_status: str) -> str:
        if provider_status in {"active", "trialing"}:
            return "active"
        if provider_status in {"past_due", "unpaid", "incomplete"}:
            return "past_due"
        if provider_status in {"canceled", "incomplete_expired"}:
            return "cancelled"
        if provider_status == "paused":
            return "paused"
        return "not_configured"

    @staticmethod
    def _tenant_id(resource) -> UUID | None:
        raw = resource.get("metadata", {}).get("tenant_id") or resource.get(
            "client_reference_id"
        )
        try:
            return UUID(str(raw)) if raw else None
        except ValueError:
            return None

    @staticmethod
    def _price_for_currency(currency: str) -> str:
        price_id = {
            "BRL": settings.STRIPE_PRICE_BRL,
            "USD": settings.STRIPE_PRICE_USD,
            "JPY": settings.STRIPE_PRICE_JPY,
        }.get(currency)
        if not price_id:
            raise WorkflowError(f"Stripe price is not configured for {currency}", 503)
        return price_id

    @staticmethod
    def _configure_stripe(require_webhook: bool = False) -> None:
        if not settings.STRIPE_SECRET_KEY:
            raise WorkflowError("Stripe is not configured", 503)
        if require_webhook and not settings.STRIPE_WEBHOOK_SECRET:
            raise WorkflowError("Stripe webhook is not configured", 503)
        stripe.api_key = settings.STRIPE_SECRET_KEY

    @staticmethod
    def _account_entity(database, tenant_id: UUID) -> BillingAccountEntity:
        account = database.scalar(
            select(BillingAccountEntity).where(
                BillingAccountEntity.tenant_id == tenant_id,
                BillingAccountEntity.deleted_at.is_(None),
            )
        )
        if account is None:
            account = BillingAccountEntity(tenant_id=tenant_id, status="not_configured")
            database.add(account)
            database.flush()
        return account

    @staticmethod
    def _account(tenant_id: UUID, subject: str, roles: set[str]) -> BillingAccountRead:
        with SessionLocal.begin() as database:
            tenant_service.require_role(database, tenant_id, subject, roles)
            account = BillingService._account_entity(database, tenant_id)
            return BillingAccountRead.model_validate(account)


billing_service = BillingService()
