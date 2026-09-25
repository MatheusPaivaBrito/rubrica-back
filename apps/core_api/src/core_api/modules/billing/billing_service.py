import logging
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
from core_api.modules.billing.notification_client import (
    BillingEmailDeliveryError,
    request_billing_email,
)
from core_api.modules.billing.providers import billing_provider
from core_api.modules.billing.providers.protocol import (
    BillingProvider,
    BillingProviderError,
    InvalidWebhookSignatureError,
    ProviderBusinessIdentity,
)
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_service import tenant_service
from shared_kernel.time.datetime_service import DateTimeService


logger = logging.getLogger(__name__)


class BillingService:
    PLAN_FILE_LIMITS = {
        "rubrica_base": 20,
        "rubrica_intermediate": 80,
        "rubrica_team": 200,
    }
    BUSINESS_PRODUCT_CODES = frozenset({"rubrica_intermediate", "rubrica_team"})
    PLAN_MEMBER_LIMITS = {"rubrica_intermediate": 3, "rubrica_team": 10}

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

    def synchronize_account(
        self,
        tenant_id: UUID,
        subject: str,
    ) -> BillingAccountRead:
        provider = self._get_provider()
        notification: tuple[str, object, str | None, str | None] | None = None
        with SessionLocal.begin() as database:
            tenant_service.require_role(database, tenant_id, subject, {"admin"})
            account = self._account_entity(database, tenant_id, lock=True)
            if not account.provider_subscription_id:
                raise WorkflowError("Stripe subscription is not configured", 409)
            previous_status = account.status
            previous_product = self._normalize_product_code(
                account.current_product_code
            )
            try:
                resource = provider.retrieve_subscription(
                    account.provider_subscription_id
                )
                business_identity = (
                    provider.retrieve_customer_business_identity(
                        account.provider_customer_id
                    )
                    if account.provider_customer_id
                    and self._product_code(resource) in self.BUSINESS_PRODUCT_CODES
                    else None
                )
            except BillingProviderError as exc:
                raise WorkflowError(str(exc), 502) from exc
            self._apply_event(
                database,
                "customer.subscription.updated",
                resource,
                tenant_id,
                business_identity=business_identity,
            )
            current_product = self._normalize_product_code(
                account.current_product_code
            )
            if current_product != previous_product:
                notification = (
                    f"sync:{account.provider_subscription_id}:{current_product}",
                    resource,
                    previous_status,
                    previous_product,
                )
        if notification is not None:
            event_id, resource, previous_status, previous_product = notification
            try:
                with SessionLocal() as database:
                    self._notify_billing_event(
                        database,
                        event_id,
                        "customer.subscription.updated",
                        tenant_id,
                        resource,
                        previous_status,
                        previous_product,
                    )
            except BillingEmailDeliveryError:
                logger.exception(
                    "Billing plan was synchronized, but its notification could not be delivered",
                    extra={"tenant_id": str(tenant_id), "event_id": event_id},
                )
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
        if self._has_unlimited_signatures(account) or self._paid_access_enabled(account):
            return
        if account.signatures_used >= account.free_signatures_limit:
            raise WorkflowError(
                "Free signature allowance exhausted. An active subscription is required",
                402,
            )
        account.signatures_used += 1

    def consume_document(self, database, tenant_id: UUID) -> None:
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
        if getattr(account, "complimentary_lifetime", False):
            return
        limit = self._active_plan_file_limit(account)
        if limit is None:
            return
        if account.files_uploaded_in_period >= limit:
            raise WorkflowError(
                "Monthly file allowance exhausted. Wait for the next billing period or change plan",
                402,
            )
        account.files_uploaded_in_period += 1

    def create_checkout(
        self, tenant_id: UUID, subject: str, product_code: str, billing_interval: str = "month"
    ) -> BillingCheckoutRead:
        provider = self._get_provider()
        with SessionLocal.begin() as database:
            tenant_service.require_role(database, tenant_id, subject, {"admin"})
            tenant = database.get(TenantEntity, tenant_id)
            if tenant is None or tenant.deleted_at is not None:
                raise WorkflowError("Tenant not found", 404)
            account = self._account_entity(database, tenant_id)
            if account.complimentary_lifetime:
                raise WorkflowError(
                    "This account already has complimentary lifetime access",
                    409,
                )
            if self._subscription_requires_portal(account):
                raise WorkflowError(
                    "Use the billing portal to change the existing subscription",
                    409,
                )
            price_id = self._price_for_currency(tenant.currency, product_code, billing_interval)
            try:
                if not account.provider_customer_id:
                    customer = provider.create_customer(
                        email=subject,
                        name=tenant.name,
                        metadata={"tenant_id": str(tenant.id)},
                    )
                    account.provider = settings.BILLING_PROVIDER
                    account.provider_customer_id = customer.id
                checkout = provider.create_checkout_session(
                    customer_id=account.provider_customer_id,
                    price_id=price_id,
                    product_code=product_code,
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
                return_url = f"{settings.PUBLIC_WEB_URL.rstrip('/')}/plan"
                portal = provider.create_portal_session(
                    customer_id=account.provider_customer_id,
                    return_url=return_url,
                    subscription_id=(
                        account.provider_subscription_id
                        if account.status == "active"
                        else None
                    ),
                    completion_url=(
                        f"{return_url}?billing=updated&from_plan="
                        f"{self._normalize_product_code(account.current_product_code)}"
                    ),
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
        business_identity = None
        if (
            tenant_id is not None
            and resource.get("customer")
            and event_type
            in {
                "checkout.session.completed",
                "customer.subscription.created",
                "customer.subscription.updated",
            }
            and self._product_code(resource) in self.BUSINESS_PRODUCT_CODES
        ):
            try:
                business_identity = provider.retrieve_customer_business_identity(
                    str(resource["customer"])
                )
            except BillingProviderError as exc:
                raise WorkflowError(str(exc), 503) from exc
        sanitized = {
            "type": event_type,
            "resource_id": resource_id,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "customer_id": resource.get("customer"),
            "subscription_id": resource.get("subscription"),
            "status": resource.get("status"),
            "cancel_at_period_end": resource.get("cancel_at_period_end"),
            "cancel_at": resource.get("cancel_at"),
            "price_id": self._subscription_price_id(resource),
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
                previous_account = (
                    self._account_entity(database, tenant_id)
                    if tenant_id is not None
                    else None
                )
                previous_status = previous_account.status if previous_account else None
                previous_product = (
                    self._normalize_product_code(
                        previous_account.current_product_code
                    )
                    if previous_account
                    else None
                )
                applied = self._apply_event(
                    database,
                    event_type,
                    resource,
                    tenant_id,
                    event_created_at,
                    event_id,
                    business_identity,
                )
                if applied:
                    self._notify_billing_event(
                        database,
                        event_id,
                        event_type,
                        tenant_id,
                        resource,
                        previous_status,
                        previous_product,
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
        previous_product: str | None,
    ) -> None:
        if tenant_id is None:
            return
        tenant = database.get(TenantEntity, tenant_id)
        if tenant is None:
            return
        provider_status = str(resource.get("status", ""))
        current_product = BillingService._product_code(resource)
        message = BillingService._billing_message(
            tenant.default_locale,
            event_type,
            provider_status,
            previous_status,
            previous_product,
            current_product,
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
        subject, body, eyebrow = message
        for recipient in recipients:
            recipient_key = sha256(recipient.encode()).hexdigest()[:16]
            request_billing_email(
                recipient=recipient,
                subject=subject,
                body=body.format(tenant=tenant.name),
                idempotency_key=f"stripe:{event_id}:{recipient_key}",
                eyebrow=eyebrow,
            )

    @staticmethod
    def _billing_message(
        locale: str,
        event_type: str,
        provider_status: str = "",
        previous_status: str | None = None,
        previous_product: str | None = None,
        current_product: str | None = None,
    ) -> tuple[str, str, str] | None:
        key = {
            "checkout.session.completed": "checkout",
            "invoice.payment_succeeded": "paid",
            "invoice.payment_failed": "failed",
        }.get(event_type)
        if event_type.startswith("customer.subscription."):
            mapped_status = BillingService._subscription_status(provider_status)
            product_changed = bool(
                event_type == "customer.subscription.updated"
                and previous_product
                and current_product
                and previous_product != current_product
            )
            if product_changed:
                key = "plan_changed"
            elif event_type != "customer.subscription.created" and mapped_status == previous_status:
                return None
            else:
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
                "checkout": ("Rubrica payment received", "We received the checkout for {tenant}. The monthly file allowance will be enabled after Stripe confirms the subscription."),
                "active": ("Rubrica subscription active", "The subscription for {tenant} is active. Its monthly file allowance is available."),
                "cancelled": ("Rubrica subscription cancelled", "The subscription for {tenant} was cancelled."),
                "paid": ("Rubrica payment confirmed", "Stripe confirmed the payment for {tenant}."),
                "failed": ("Rubrica payment failed", "Stripe could not confirm the payment for {tenant}. Please review your payment method in the billing portal."),
                "paused": ("Rubrica subscription paused", "The subscription for {tenant} was paused. Review its status in the billing portal."),
                "plan_changed": ("Rubrica plan updated", "The plan for {tenant} was updated from {previous_plan} to {current_plan}. The new allowance is {limit} PDFs per billing period, and current usage was preserved."),
            },
            "pt-BR": {
                "checkout": ("Pagamento recebido pelo Rubrica", "Recebemos o checkout de {tenant}. A franquia mensal de arquivos será liberada após a confirmação do Stripe."),
                "active": ("Assinatura Rubrica ativa", "A assinatura de {tenant} está ativa. A franquia mensal de arquivos está disponível."),
                "cancelled": ("Assinatura Rubrica cancelada", "A assinatura de {tenant} foi cancelada."),
                "paid": ("Pagamento Rubrica confirmado", "O Stripe confirmou o pagamento de {tenant}."),
                "failed": ("Falha no pagamento Rubrica", "O Stripe não confirmou o pagamento de {tenant}. Revise a forma de pagamento no portal de cobrança."),
                "paused": ("Assinatura Rubrica pausada", "A assinatura de {tenant} foi pausada. Revise a situação no portal de cobrança."),
                "plan_changed": ("Plano Rubrica atualizado", "O plano de {tenant} foi atualizado de {previous_plan} para {current_plan}. A nova franquia é de {limit} PDFs por período, e o uso atual foi preservado."),
            },
            "ja-JP": {
                "checkout": ("Rubrica お支払い受付", "{tenant} のチェックアウトを受け付けました。Stripe の確認後、月間ファイル枠が有効になります。"),
                "active": ("Rubrica サブスクリプション有効", "{tenant} のサブスクリプションが有効になり、月間ファイル枠を利用できます。"),
                "cancelled": ("Rubrica サブスクリプション解約", "{tenant} のサブスクリプションは解約されました。"),
                "paid": ("Rubrica お支払い確認", "Stripe が {tenant} のお支払いを確認しました。"),
                "failed": ("Rubrica お支払い失敗", "{tenant} のお支払いを確認できませんでした。請求ポータルでお支払い方法をご確認ください。"),
                "paused": ("Rubrica サブスクリプション一時停止", "{tenant} のサブスクリプションは一時停止されています。請求ポータルで状態をご確認ください。"),
                "plan_changed": ("Rubrica プラン更新", "{tenant} のプランが {previous_plan} から {current_plan} に更新されました。新しい上限は請求期間ごとに PDF {limit} 件で、現在の利用数は引き継がれます。"),
            },
            "es": {
                "checkout": ("Pago recibido por Rubrica", "Recibimos el pago de {tenant}. La cuota mensual de archivos se habilitará cuando Stripe confirme la suscripción."),
                "active": ("Suscripción Rubrica activa", "La suscripción de {tenant} está activa y su cuota mensual de archivos está disponible."),
                "cancelled": ("Suscripción Rubrica cancelada", "La suscripción de {tenant} fue cancelada."),
                "paid": ("Pago Rubrica confirmado", "Stripe confirmó el pago de {tenant}."),
                "failed": ("Error en el pago de Rubrica", "Stripe no pudo confirmar el pago de {tenant}. Revisa el método de pago en el portal de facturación."),
                "paused": ("Suscripción Rubrica pausada", "La suscripción de {tenant} fue pausada. Revisa su estado en el portal de facturación."),
                "plan_changed": ("Plan Rubrica actualizado", "El plan de {tenant} se actualizó de {previous_plan} a {current_plan}. El nuevo límite es de {limit} PDF por período y se conservó el uso actual."),
            },
        }
        subject, body = messages.get(locale, messages["en"])[key]
        if key != "plan_changed":
            return subject, body, "RUBRICA NOTIFICATION"
        plan_names = {
            "en": {"rubrica_base": "Essential", "rubrica_intermediate": "Professional", "rubrica_team": "Team"},
            "pt-BR": {"rubrica_base": "Essencial", "rubrica_intermediate": "Profissional", "rubrica_team": "Equipe"},
            "es": {"rubrica_base": "Esencial", "rubrica_intermediate": "Profesional", "rubrica_team": "Equipo"},
            "ja-JP": {"rubrica_base": "エッセンシャル", "rubrica_intermediate": "プロフェッショナル", "rubrica_team": "チーム"},
        }
        names = plan_names.get(locale, plan_names["en"])
        normalized_previous = BillingService._normalize_product_code(previous_product)
        normalized_current = BillingService._normalize_product_code(current_product)
        return (
            subject,
            body.format(
                previous_plan=names.get(normalized_previous, normalized_previous),
                current_plan=names.get(normalized_current, normalized_current),
                limit=BillingService.PLAN_FILE_LIMITS.get(normalized_current, 0),
                tenant="{tenant}",
            ),
            {
                "pt-BR": "ATUALIZAÇÃO DE PLANO",
                "es": "ACTUALIZACIÓN DEL PLAN",
                "ja-JP": "プラン更新",
            }.get(locale, "PLAN UPDATE"),
        )

    @staticmethod
    def _apply_event(
        database, event_type: str, resource, tenant_id: UUID | None,
        event_created_at: datetime | None = None,
        provider_event_id: str = "",
        business_identity: ProviderBusinessIdentity | None = None,
    ) -> bool:
        if tenant_id is None:
            return True
        account = BillingService._account_entity(database, tenant_id, lock=True)
        account.provider = "stripe"
        customer = resource.get("customer")
        if customer:
            account.provider_customer_id = str(customer)
        if event_type == "checkout.session.completed":
            subscription = resource.get("subscription")
            account.provider_subscription_id = (
                str(subscription) if subscription else None
            )
            account.current_product_code = BillingService._product_code(resource)
            if account.status != "active":
                account.status = "pending"
            BillingService._apply_business_identity(
                database, tenant_id, account.current_product_code, business_identity
            )
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
                period_start, period_end = BillingService._invoice_service_period(
                    resource
                )
                BillingService._sync_usage_period(
                    account,
                    period_start,
                    period_end,
                    reset_usage=(
                        resource.get("billing_reason") == "subscription_cycle"
                    ),
                )
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
            account.current_product_code = BillingService._product_code(resource)
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
            period_start, period_end = BillingService._subscription_period(resource)
            account.cancel_at_period_end = bool(
                resource.get("cancel_at_period_end", False)
            )
            account.cancels_at = (
                BillingService._timestamp(resource.get("cancel_at")) or period_end
                if account.cancel_at_period_end
                else None
            )
            if account.status == "active":
                BillingService._sync_usage_period(
                    account,
                    period_start,
                    period_end,
                    reset_usage=False,
                )
            elif period_end is not None:
                account.current_period_ends_at = period_end
            BillingService._apply_business_identity(
                database, tenant_id, account.current_product_code, business_identity
            )
        return True

    @staticmethod
    def _apply_business_identity(
        database,
        tenant_id: UUID,
        product_code: str | None,
        identity: ProviderBusinessIdentity | None,
    ) -> None:
        if (
            identity is None
            or BillingService._normalize_product_code(product_code)
            not in BillingService.BUSINESS_PRODUCT_CODES
        ):
            return
        cnpj = next(
            (tax_id for tax_id in identity.tax_ids if tax_id.type == "br_cnpj"),
            None,
        ) if identity is not None else None
        tenant_service.apply_billing_business_identity(
            database,
            tenant_id,
            legal_name=identity.name if identity is not None else None,
            cnpj=cnpj.value if cnpj is not None else None,
            provider_reference=cnpj.id if cnpj is not None else None,
        )

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
        return bool(getattr(account, "complimentary_lifetime", False))

    @staticmethod
    def _paid_access_enabled(account: BillingAccountEntity) -> bool:
        if account.status == "active":
            return True
        grace = getattr(account, "grace_period_ends_at", None)
        if account.status != "past_due" or grace is None:
            return False
        if grace.tzinfo is None:
            grace = grace.replace(tzinfo=UTC)
        return grace > DateTimeService.utc_now()

    @staticmethod
    def _active_plan_file_limit(account: BillingAccountEntity) -> int | None:
        if not BillingService._paid_access_enabled(account):
            return None
        return BillingService.PLAN_FILE_LIMITS.get(
            BillingService._normalize_product_code(account.current_product_code)
        )

    @staticmethod
    def _subscription_requires_portal(account: BillingAccountEntity) -> bool:
        return bool(
            account.provider_subscription_id
            and account.status in {"active", "pending", "past_due", "unpaid", "paused"}
        )

    @staticmethod
    def _normalize_product_code(product_code: object) -> str:
        value = str(product_code or "rubrica_base")
        return "rubrica_base" if value == "rubrica_mvp" else value

    @staticmethod
    def _product_code(resource) -> str:
        configured_prices = {
            price_id: product_code
            for product_code, price_ids in {
                "rubrica_base": (
                    settings.STRIPE_PRICE_BRL,
                    settings.STRIPE_PRICE_USD,
                    settings.STRIPE_PRICE_EUR,
                    settings.STRIPE_PRICE_JPY,
                    settings.STRIPE_PRICE_ANNUAL_BRL,
                    settings.STRIPE_PRICE_ANNUAL_USD,
                    settings.STRIPE_PRICE_ANNUAL_EUR,
                    settings.STRIPE_PRICE_ANNUAL_JPY,
                ),
                "rubrica_intermediate": (
                    settings.STRIPE_PRICE_INTERMEDIATE_BRL,
                    settings.STRIPE_PRICE_INTERMEDIATE_USD,
                    settings.STRIPE_PRICE_INTERMEDIATE_EUR,
                    settings.STRIPE_PRICE_INTERMEDIATE_JPY,
                    settings.STRIPE_PRICE_INTERMEDIATE_ANNUAL_BRL,
                    settings.STRIPE_PRICE_INTERMEDIATE_ANNUAL_USD,
                    settings.STRIPE_PRICE_INTERMEDIATE_ANNUAL_EUR,
                    settings.STRIPE_PRICE_INTERMEDIATE_ANNUAL_JPY,
                ),
                "rubrica_team": (
                    settings.STRIPE_PRICE_TEAM_BRL,
                    settings.STRIPE_PRICE_TEAM_USD,
                    settings.STRIPE_PRICE_TEAM_EUR,
                    settings.STRIPE_PRICE_TEAM_JPY,
                    settings.STRIPE_PRICE_TEAM_ANNUAL_BRL,
                    settings.STRIPE_PRICE_TEAM_ANNUAL_USD,
                    settings.STRIPE_PRICE_TEAM_ANNUAL_EUR,
                    settings.STRIPE_PRICE_TEAM_ANNUAL_JPY,
                ),
            }.items()
            for price_id in price_ids
            if price_id
        }
        price_id = BillingService._subscription_price_id(resource)
        if price_id in configured_prices:
            return configured_prices[price_id]
        metadata_code = (resource.get("metadata") or {}).get("product_code")
        normalized = BillingService._normalize_product_code(metadata_code)
        return (
            normalized
            if normalized in BillingService.PLAN_FILE_LIMITS
            else "rubrica_base"
        )

    @staticmethod
    def _subscription_price_id(resource) -> str | None:
        for item in (resource.get("items") or {}).get("data") or []:
            price = item.get("price") or item.get("plan") or {}
            price_id = str(price.get("id") or "")
            if price_id:
                return price_id
        return None

    @staticmethod
    def _subscription_period(resource) -> tuple[datetime | None, datetime | None]:
        start = resource.get("current_period_start")
        end = resource.get("current_period_end")
        if not start or not end:
            items = (resource.get("items") or {}).get("data") or []
            if items:
                start = start or items[0].get("current_period_start")
                end = end or items[0].get("current_period_end")
        return BillingService._timestamp(start), BillingService._timestamp(end)

    @staticmethod
    def _sync_usage_period(
        account: BillingAccountEntity,
        period_start: datetime | None,
        period_end: datetime | None,
        *,
        reset_usage: bool,
    ) -> None:
        if period_end is not None:
            account.current_period_ends_at = period_end
        if period_start is None:
            return
        current_start = getattr(account, "usage_period_starts_at", None)
        if current_start is not None and current_start.tzinfo is None:
            current_start = current_start.replace(tzinfo=UTC)
        if (
            reset_usage
            and current_start is not None
            and period_start > current_start
        ):
            account.files_uploaded_in_period = 0
        if current_start is None or (
            reset_usage and period_start > current_start
        ):
            account.usage_period_starts_at = period_start

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
    def _price_for_currency(currency: str, product_code: str = "rubrica_base", billing_interval: str = "month") -> str:
        prices = {
            "rubrica_base": {
                "month": {"BRL": settings.STRIPE_PRICE_BRL, "USD": settings.STRIPE_PRICE_USD, "EUR": settings.STRIPE_PRICE_EUR, "JPY": settings.STRIPE_PRICE_JPY},
                "year": {"BRL": settings.STRIPE_PRICE_ANNUAL_BRL, "USD": settings.STRIPE_PRICE_ANNUAL_USD, "EUR": settings.STRIPE_PRICE_ANNUAL_EUR, "JPY": settings.STRIPE_PRICE_ANNUAL_JPY},
            },
            "rubrica_intermediate": {
                "month": {"BRL": settings.STRIPE_PRICE_INTERMEDIATE_BRL, "USD": settings.STRIPE_PRICE_INTERMEDIATE_USD, "EUR": settings.STRIPE_PRICE_INTERMEDIATE_EUR, "JPY": settings.STRIPE_PRICE_INTERMEDIATE_JPY},
                "year": {"BRL": settings.STRIPE_PRICE_INTERMEDIATE_ANNUAL_BRL, "USD": settings.STRIPE_PRICE_INTERMEDIATE_ANNUAL_USD, "EUR": settings.STRIPE_PRICE_INTERMEDIATE_ANNUAL_EUR, "JPY": settings.STRIPE_PRICE_INTERMEDIATE_ANNUAL_JPY},
            },
            "rubrica_team": {
                "month": {"BRL": settings.STRIPE_PRICE_TEAM_BRL, "USD": settings.STRIPE_PRICE_TEAM_USD, "EUR": settings.STRIPE_PRICE_TEAM_EUR, "JPY": settings.STRIPE_PRICE_TEAM_JPY},
                "year": {"BRL": settings.STRIPE_PRICE_TEAM_ANNUAL_BRL, "USD": settings.STRIPE_PRICE_TEAM_ANNUAL_USD, "EUR": settings.STRIPE_PRICE_TEAM_ANNUAL_EUR, "JPY": settings.STRIPE_PRICE_TEAM_ANNUAL_JPY},
            },
        }
        configured = prices.get(product_code, {}).get(billing_interval, {})
        price_id = configured.get(currency.upper())
        if not price_id:
            raise WorkflowError(
                f"Stripe price is not configured for {product_code} in {currency}",
                503,
            )
        return price_id

    @staticmethod
    def business_features_enabled(database, tenant_id: UUID) -> bool:
        account = database.scalar(
            select(BillingAccountEntity).where(
                BillingAccountEntity.tenant_id == tenant_id,
                BillingAccountEntity.deleted_at.is_(None),
            )
        )
        return bool(
            account
            and (
                getattr(account, "complimentary_lifetime", False)
                or (
                    BillingService._normalize_product_code(account.current_product_code)
                    in BillingService.BUSINESS_PRODUCT_CODES
                    and BillingService._paid_access_enabled(account)
                )
            )
        )

    @staticmethod
    def email_invitations_enabled(database, tenant_id: UUID) -> bool:
        account = database.scalar(
            select(BillingAccountEntity).where(
                BillingAccountEntity.tenant_id == tenant_id,
                BillingAccountEntity.deleted_at.is_(None),
            )
        )
        return bool(
            account
            and (
                getattr(account, "complimentary_lifetime", False)
                or (
                    BillingService._normalize_product_code(account.current_product_code)
                    in BillingService.BUSINESS_PRODUCT_CODES
                    and BillingService._paid_access_enabled(account)
                )
            )
        )

    @staticmethod
    def _account_entity(
        database,
        tenant_id: UUID,
        *,
        lock: bool = False,
    ) -> BillingAccountEntity:
        statement = select(BillingAccountEntity).where(
            BillingAccountEntity.tenant_id == tenant_id
        )
        if lock:
            statement = statement.with_for_update()
        account = database.scalar(statement)
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
            paid_access = BillingService._paid_access_enabled(account)
            files_limit = BillingService._active_plan_file_limit(account)
            unlimited_files = bool(account.complimentary_lifetime)
            return BillingAccountRead(
                id=account.id,
                tenant_id=account.tenant_id,
                status=account.status,
                provider=account.provider,
                provider_customer_id=account.provider_customer_id,
                provider_subscription_id=account.provider_subscription_id,
                current_product_code=account.current_product_code,
                current_period_ends_at=account.current_period_ends_at,
                cancel_at_period_end=account.cancel_at_period_end,
                cancels_at=account.cancels_at,
                grace_period_ends_at=account.grace_period_ends_at,
                free_signatures_limit=account.free_signatures_limit,
                signatures_used=account.signatures_used,
                signatures_remaining=(
                    None
                    if unlimited or paid_access
                    else max(account.free_signatures_limit - account.signatures_used, 0)
                ),
                unlimited_signatures=unlimited,
                files_uploaded_in_period=account.files_uploaded_in_period,
                files_limit=files_limit,
                files_remaining=(
                    None
                    if unlimited_files or files_limit is None
                    else max(files_limit - account.files_uploaded_in_period, 0)
                ),
                unlimited_files=unlimited_files,
                email_invitations_enabled=(
                    account.complimentary_lifetime
                    or (
                        BillingService._normalize_product_code(
                            account.current_product_code
                        )
                        in BillingService.BUSINESS_PRODUCT_CODES
                        and BillingService._paid_access_enabled(account)
                    )
                ),
                usage_period_starts_at=account.usage_period_starts_at,
                complimentary_lifetime=account.complimentary_lifetime,
                created_at=account.created_at,
            )


billing_service = BillingService()
