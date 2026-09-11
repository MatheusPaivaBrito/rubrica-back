from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import (
    BillingAccountEntity,
    BillingEventEntity,
)
from core_api.modules.billing.billing_schema import (
    BillingAccountRead,
    BillingCheckoutRead,
    BillingPortalRead,
    BillingWebhookRead,
)
from core_api.modules.billing.providers import billing_provider
from core_api.modules.billing.providers.protocol import (
    BillingProvider,
    BillingProviderError,
    InvalidWebhookSignatureError,
)
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import TenantEntity
from core_api.modules.tenant.tenant_service import tenant_service
from shared_kernel.time.datetime_service import DateTimeService


class BillingService:
    def __init__(self, provider: BillingProvider | None = None) -> None:
        self._provider = provider

    def _get_provider(self) -> BillingProvider:
        try:
            return self._provider or billing_provider()
        except BillingProviderError as exc:
            raise WorkflowError(str(exc), 503) from exc

    def account(self, tenant_id: UUID, subject: str) -> BillingAccountRead:
        return self._account(tenant_id, subject, {"admin", "auditor"})

    def initialize(self, tenant_id: UUID, subject: str) -> BillingAccountRead:
        return self._account(tenant_id, subject, {"admin"})

    def consume_signature(self, database, tenant_id: UUID) -> None:
        account = database.scalar(
            select(BillingAccountEntity)
            .where(BillingAccountEntity.tenant_id == tenant_id)
            .with_for_update()
        )
        if account is None:
            account = BillingAccountEntity(tenant_id=tenant_id, status="not_configured")
            database.add(account)
            database.flush()
        elif account.deleted_at is not None:
            account.deleted_at = None
        if (
            not self._has_unlimited_signatures(account)
            and account.signatures_used >= account.free_signatures_limit
        ):
            raise WorkflowError(
                "Free signature allowance exhausted. An active subscription is required",
                402,
            )
        account.signatures_used += 1

    def create_checkout(self, tenant_id: UUID, subject: str) -> BillingCheckoutRead:
        provider = self._get_provider()
        with SessionLocal.begin() as database:
            tenant_service.require_role(database, tenant_id, subject, {"admin"})
            tenant = database.get(TenantEntity, tenant_id)
            if tenant is None or tenant.deleted_at is not None:
                raise WorkflowError("Tenant not found", 404)
            price_id = self._price_for_currency(tenant.currency)
            account = self._account_entity(database, tenant_id)
            try:
                if not account.provider_customer_id:
                    customer = provider.create_customer(
                        email=subject,
                        name=tenant.name,
                        metadata={"tenant_id": str(tenant.id)},
                    )
                    account.provider = "stripe"
                    account.provider_customer_id = customer.id
                checkout = provider.create_checkout_session(
                    customer_id=account.provider_customer_id,
                    price_id=price_id,
                    tenant_id=str(tenant.id),
                    success_url=f"{settings.PUBLIC_WEB_URL.rstrip('/')}/plan?checkout=success",
                    cancel_url=f"{settings.PUBLIC_WEB_URL.rstrip('/')}/plan?checkout=cancelled",
                )
            except BillingProviderError as exc:
                raise WorkflowError(str(exc), 502) from exc
            return BillingCheckoutRead(checkout_url=checkout.url)

    def create_portal(self, tenant_id: UUID, subject: str) -> BillingPortalRead:
        provider = self._get_provider()
        with SessionLocal.begin() as database:
            tenant_service.require_role(database, tenant_id, subject, {"admin"})
            account = self._account_entity(database, tenant_id)
            if not account.provider_customer_id:
                raise WorkflowError("Stripe customer is not configured", 409)
            try:
                portal = provider.create_portal_session(
                    customer_id=account.provider_customer_id,
                    return_url=f"{settings.PUBLIC_WEB_URL.rstrip('/')}/plan",
                )
            except BillingProviderError as exc:
                raise WorkflowError(str(exc), 502) from exc
            return BillingPortalRead(portal_url=portal.url)

    def receive_webhook(self, payload: bytes, signature: str) -> BillingWebhookRead:
        provider = self._get_provider()
        try:
            event = provider.construct_webhook_event(
                payload=payload,
                signature=signature,
            )
        except InvalidWebhookSignatureError as exc:
            raise WorkflowError("Invalid Stripe webhook signature", 400) from exc
        except BillingProviderError as exc:
            raise WorkflowError(str(exc), 503) from exc

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
        event_created_at = self._event_created_at(event)
        if tenant_id is None and resource.get("customer"):
            with SessionLocal() as database:
                tenant_id = database.scalar(
                    select(BillingAccountEntity.tenant_id).where(
                        BillingAccountEntity.provider_customer_id == str(resource["customer"])
                    )
                )
        sanitized = {
            "type": event_type,
            "resource_id": resource_id,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "customer_id": resource.get("customer"),
            "subscription_id": resource.get("subscription"),
            "status": resource.get("status"),
            "event_created_at": event_created_at.isoformat(),
        }
        try:
            with SessionLocal.begin() as database:
                database.add(BillingEventEntity(
                    tenant_id=tenant_id,
                    provider="stripe",
                    provider_event_id=event_id,
                    event_type=event_type,
                    resource_id=resource_id,
                    payload_hash=sha256(payload).hexdigest(),
                    payload_sanitized=sanitized,
                    status="received",
                ))
        except IntegrityError:
            return BillingWebhookRead(duplicate=True)

        try:
            with SessionLocal.begin() as database:
                billing_event = database.scalar(
                    select(BillingEventEntity)
                    .where(
                        BillingEventEntity.provider == "stripe",
                        BillingEventEntity.provider_event_id == event_id,
                    )
                    .with_for_update()
                )
                if billing_event is None:
                    raise WorkflowError("Persisted billing event was not found", 500)
                if billing_event.status != "received":
                    return BillingWebhookRead(duplicate=True)
                applied = self._apply_event(database, event_type, resource, tenant_id, event_created_at)
                billing_event.status = "processed" if applied else "ignored_stale"
                billing_event.processed_at = DateTimeService.utc_now()
        except Exception as exc:
            with SessionLocal.begin() as database:
                failed_event = database.scalar(
                    select(BillingEventEntity)
                    .where(
                        BillingEventEntity.provider == "stripe",
                        BillingEventEntity.provider_event_id == event_id,
                    )
                    .with_for_update()
                )
                if failed_event is not None:
                    failed_event.status = "failed"
                    failed_event.error_code = type(exc).__name__[:120]
            raise
        return BillingWebhookRead()

    @staticmethod
    def _apply_event(
        database, event_type: str, resource, tenant_id: UUID | None,
        event_created_at: datetime | None = None,
    ) -> bool:
        if tenant_id is None:
            return True
        account = BillingService._account_entity(database, tenant_id)
        account.provider = "stripe"
        customer = resource.get("customer")
        if customer:
            account.provider_customer_id = str(customer)
        if event_type == "checkout.session.completed":
            subscription = resource.get("subscription")
            account.provider_subscription_id = (
                str(subscription) if subscription else None
            )
            account.current_product_code = "rubrica_mvp"
            if account.status != "active":
                account.status = "pending"
            return True
        if event_type.startswith("customer.subscription."):
            if (
                event_created_at
                and getattr(account, "last_provider_event_created_at", None)
                and event_created_at < account.last_provider_event_created_at
            ):
                return False
            account.provider_subscription_id = str(resource.get("id"))
            account.current_product_code = str(
                resource.get("metadata", {}).get("product_code", "rubrica_mvp")
            )
            account.status = BillingService._subscription_status(
                str(resource.get("status", ""))
            )
            if account.status == "past_due":
                account.grace_period_ends_at = DateTimeService.utc_now() + timedelta(
                    days=settings.BILLING_GRACE_PERIOD_DAYS
                )
            elif account.status in {"active", "cancelled"}:
                account.grace_period_ends_at = None
            if event_created_at:
                account.last_provider_event_created_at = event_created_at
            period_end = resource.get("current_period_end")
            account.current_period_ends_at = (
                datetime.fromtimestamp(int(period_end), tz=UTC) if period_end else None
            )
        return True

    @staticmethod
    def _event_created_at(event) -> datetime:
        raw = event.get("created")
        if raw is None:
            return DateTimeService.utc_now()
        return datetime.fromtimestamp(int(raw), tz=UTC)

    @staticmethod
    def _has_unlimited_signatures(account: BillingAccountEntity) -> bool:
        if account.status == "active":
            return True
        grace = getattr(account, "grace_period_ends_at", None)
        if account.status != "past_due" or grace is None:
            return False
        if grace.tzinfo is None:
            grace = grace.replace(tzinfo=UTC)
        return grace > DateTimeService.utc_now()

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
    def _account_entity(database, tenant_id: UUID) -> BillingAccountEntity:
        account = database.scalar(
            select(BillingAccountEntity).where(
                BillingAccountEntity.tenant_id == tenant_id
            )
        )
        if account is None:
            account = BillingAccountEntity(tenant_id=tenant_id, status="not_configured")
            database.add(account)
            database.flush()
        elif account.deleted_at is not None:
            account.deleted_at = None
        return account

    @staticmethod
    def _account(tenant_id: UUID, subject: str, roles: set[str]) -> BillingAccountRead:
        with SessionLocal.begin() as database:
            tenant_service.require_role(database, tenant_id, subject, roles)
            account = BillingService._account_entity(database, tenant_id)
            unlimited = BillingService._has_unlimited_signatures(account)
            return BillingAccountRead(
                id=account.id,
                tenant_id=account.tenant_id,
                status=account.status,
                provider=account.provider,
                provider_customer_id=account.provider_customer_id,
                provider_subscription_id=account.provider_subscription_id,
                current_product_code=account.current_product_code,
                current_period_ends_at=account.current_period_ends_at,
                grace_period_ends_at=account.grace_period_ends_at,
                free_signatures_limit=account.free_signatures_limit,
                signatures_used=account.signatures_used,
                signatures_remaining=(
                    None
                    if unlimited
                    else max(account.free_signatures_limit - account.signatures_used, 0)
                ),
                unlimited_signatures=unlimited,
                created_at=account.created_at,
            )


billing_service = BillingService()
