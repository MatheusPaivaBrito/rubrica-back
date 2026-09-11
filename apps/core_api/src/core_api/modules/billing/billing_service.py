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
    BillingPaymentEntity,
)
from core_api.modules.billing.billing_schema import (
    BillingAccountRead,
    BillingCheckoutRead,
    BillingPortalRead,
    BillingPaymentRead,
    BillingWebhookRead,
)
from core_api.modules.billing.notification_client import request_billing_email
from core_api.modules.billing.providers import billing_provider
from core_api.modules.billing.providers.protocol import (
    BillingProvider,
    BillingProviderError,
    InvalidWebhookSignatureError,
)
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
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

    def payments(self, tenant_id: UUID, subject: str) -> list[BillingPaymentRead]:
        with SessionLocal() as database:
            tenant_service.require_role(database, tenant_id, subject, {"admin", "auditor"})
            return [
                BillingPaymentRead.model_validate(payment)
                for payment in database.scalars(
                    select(BillingPaymentEntity)
                    .where(
                        BillingPaymentEntity.tenant_id == tenant_id,
                        BillingPaymentEntity.deleted_at.is_(None),
                    )
                    .order_by(BillingPaymentEntity.created_at.desc())
                ).all()
            ]

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
            existing_status = database.scalar(
                select(BillingEventEntity.status).where(
                    BillingEventEntity.provider == "stripe",
                    BillingEventEntity.provider_event_id == event_id,
                )
            )
        if existing_status in {"processed", "ignored_stale"}:
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
        if existing_status is None:
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
                if billing_event.status in {"processed", "ignored_stale"}:
                    return BillingWebhookRead(duplicate=True)
                previous_status = (
                    self._account_entity(database, tenant_id).status
                    if tenant_id is not None
                    else None
                )
                applied = self._apply_event(
                    database,
                    event_type,
                    resource,
                    tenant_id,
                    event_created_at,
                    event_id,
                )
                if applied:
                    self._notify_billing_event(
                        database,
                        event_id,
                        event_type,
                        tenant_id,
                        resource,
                        previous_status,
                    )
                billing_event.status = "processed" if applied else "ignored_stale"
                billing_event.processed_at = DateTimeService.utc_now()
                billing_event.error_code = None
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
    def _notify_billing_event(
        database,
        event_id: str,
        event_type: str,
        tenant_id: UUID | None,
        resource,
        previous_status: str | None,
    ) -> None:
        if tenant_id is None:
            return
        tenant = database.get(TenantEntity, tenant_id)
        if tenant is None:
            return
        provider_status = str(resource.get("status", ""))
        message = BillingService._billing_message(
            tenant.default_locale,
            event_type,
            provider_status,
            previous_status,
        )
        if message is None:
            return
        recipients = database.scalars(
            select(TenantMemberEntity.auth_user_id).where(
                TenantMemberEntity.tenant_id == tenant_id,
                TenantMemberEntity.role == "admin",
                TenantMemberEntity.deleted_at.is_(None),
            )
        ).all()
        subject, body = message
        for recipient in recipients:
            recipient_key = sha256(recipient.encode()).hexdigest()[:16]
            request_billing_email(
                recipient=recipient,
                subject=subject,
                body=body.format(tenant=tenant.name),
                idempotency_key=f"stripe:{event_id}:{recipient_key}",
            )

    @staticmethod
    def _billing_message(
        locale: str,
        event_type: str,
        provider_status: str = "",
        previous_status: str | None = None,
    ) -> tuple[str, str] | None:
        key = {
            "checkout.session.completed": "checkout",
            "invoice.payment_succeeded": "paid",
            "invoice.payment_failed": "failed",
        }.get(event_type)
        if event_type.startswith("customer.subscription."):
            mapped_status = BillingService._subscription_status(provider_status)
            if event_type != "customer.subscription.created" and mapped_status == previous_status:
                return None
            key = {
                "active": "active",
                "past_due": "failed",
                "unpaid": "failed",
                "cancelled": "cancelled",
                "paused": "paused",
            }.get(mapped_status)
        if key is None:
            return None
        messages = {
            "en": {
                "checkout": ("Rubrica payment received", "We received the checkout for {tenant}. Unlimited signatures will be enabled after Stripe confirms the subscription."),
                "active": ("Rubrica subscription active", "The subscription for {tenant} is active. Unlimited signatures are enabled."),
                "cancelled": ("Rubrica subscription cancelled", "The subscription for {tenant} was cancelled."),
                "paid": ("Rubrica payment confirmed", "Stripe confirmed the payment for {tenant}."),
                "failed": ("Rubrica payment failed", "Stripe could not confirm the payment for {tenant}. Please review your payment method in the billing portal."),
                "paused": ("Rubrica subscription paused", "The subscription for {tenant} was paused. Review its status in the billing portal."),
            },
            "pt-BR": {
                "checkout": ("Pagamento recebido pelo Rubrica", "Recebemos o checkout de {tenant}. As assinaturas ilimitadas serão liberadas após a confirmação da assinatura pelo Stripe."),
                "active": ("Assinatura Rubrica ativa", "A assinatura de {tenant} está ativa. As assinaturas ilimitadas foram liberadas."),
                "cancelled": ("Assinatura Rubrica cancelada", "A assinatura de {tenant} foi cancelada."),
                "paid": ("Pagamento Rubrica confirmado", "O Stripe confirmou o pagamento de {tenant}."),
                "failed": ("Falha no pagamento Rubrica", "O Stripe não confirmou o pagamento de {tenant}. Revise a forma de pagamento no portal de cobrança."),
                "paused": ("Assinatura Rubrica pausada", "A assinatura de {tenant} foi pausada. Revise a situação no portal de cobrança."),
            },
            "ja-JP": {
                "checkout": ("Rubrica お支払い受付", "{tenant} のチェックアウトを受け付けました。Stripe がサブスクリプションを確認した後、署名回数が無制限になります。"),
                "active": ("Rubrica サブスクリプション有効", "{tenant} のサブスクリプションが有効になりました。署名回数は無制限です。"),
                "cancelled": ("Rubrica サブスクリプション解約", "{tenant} のサブスクリプションは解約されました。"),
                "paid": ("Rubrica お支払い確認", "Stripe が {tenant} のお支払いを確認しました。"),
                "failed": ("Rubrica お支払い失敗", "{tenant} のお支払いを確認できませんでした。請求ポータルでお支払い方法をご確認ください。"),
                "paused": ("Rubrica サブスクリプション一時停止", "{tenant} のサブスクリプションは一時停止されています。請求ポータルで状態をご確認ください。"),
            },
        }
        return messages.get(locale, messages["en"])[key]

    @staticmethod
    def _apply_event(
        database, event_type: str, resource, tenant_id: UUID | None,
        event_created_at: datetime | None = None,
        provider_event_id: str = "",
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
        if event_type in {"invoice.payment_succeeded", "invoice.payment_failed"}:
            BillingService._record_payment(
                database,
                tenant_id,
                event_type,
                resource,
                provider_event_id,
            )
            if event_type == "invoice.payment_succeeded":
                account.status = "active"
                account.grace_period_ends_at = None
            elif account.status != "past_due" or account.grace_period_ends_at is None:
                account.status = "past_due"
                account.grace_period_ends_at = DateTimeService.utc_now() + timedelta(
                    days=settings.BILLING_GRACE_PERIOD_DAYS
                )
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
            if account.status == "past_due" and account.grace_period_ends_at is None:
                account.grace_period_ends_at = DateTimeService.utc_now() + timedelta(
                    days=settings.BILLING_GRACE_PERIOD_DAYS
                )
            elif account.status in {"active", "cancelled", "unpaid", "paused"}:
                account.grace_period_ends_at = None
            if event_created_at:
                account.last_provider_event_created_at = event_created_at
            period_end = resource.get("current_period_end")
            account.current_period_ends_at = (
                datetime.fromtimestamp(int(period_end), tz=UTC) if period_end else None
            )
        return True

    @staticmethod
    def _record_payment(
        database,
        tenant_id: UUID,
        event_type: str,
        resource,
        provider_event_id: str,
    ) -> None:
        provider_payment_id = str(resource.get("id", ""))
        if not provider_payment_id:
            raise WorkflowError("Stripe invoice does not include an id", 422)
        payment = database.scalar(
            select(BillingPaymentEntity).where(
                BillingPaymentEntity.provider == "stripe",
                BillingPaymentEntity.provider_payment_id == provider_payment_id,
            )
        )
        if payment is None:
            payment = BillingPaymentEntity(
                tenant_id=tenant_id,
                provider="stripe",
                provider_payment_id=provider_payment_id,
                provider_event_id=provider_event_id or event_type,
                status="pending",
                currency="USD",
                amount_due_minor=0,
                amount_paid_minor=0,
            )
            database.add(payment)
        status_transitions = resource.get("status_transitions") or {}
        parent = resource.get("parent") or {}
        subscription_details = parent.get("subscription_details") or {}
        subscription_id = resource.get("subscription") or subscription_details.get(
            "subscription"
        )
        payment.provider_subscription_id = str(subscription_id) if subscription_id else None
        payment.provider_event_id = provider_event_id or event_type
        payment.status = (
            "paid" if event_type == "invoice.payment_succeeded" else "failed"
        )
        payment.currency = str(resource.get("currency", "USD")).upper()
        payment.amount_due_minor = int(resource.get("amount_due") or 0)
        payment.amount_paid_minor = int(resource.get("amount_paid") or 0)
        period_start, period_end = BillingService._invoice_service_period(resource)
        payment.period_starts_at = period_start
        payment.period_ends_at = period_end
        payment.paid_at = BillingService._timestamp(status_transitions.get("paid_at"))

    @staticmethod
    def _timestamp(value) -> datetime | None:
        return datetime.fromtimestamp(int(value), tz=UTC) if value else None

    @staticmethod
    def _invoice_service_period(resource) -> tuple[datetime | None, datetime | None]:
        lines = (resource.get("lines") or {}).get("data") or []
        for line in lines:
            period = line.get("period") or {}
            if period.get("start") and period.get("end"):
                return (
                    BillingService._timestamp(period["start"]),
                    BillingService._timestamp(period["end"]),
                )
        return (
            BillingService._timestamp(resource.get("period_start")),
            BillingService._timestamp(resource.get("period_end")),
        )

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
        if provider_status in {"past_due", "incomplete"}:
            return "past_due"
        if provider_status == "unpaid":
            return "unpaid"
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
