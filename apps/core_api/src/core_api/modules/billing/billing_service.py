from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.auth_provisioning_client import auth_provisioning_client
from core_api.modules.billing.billing_entity import (
    BillingCheckoutSessionEntity,
    BillingEventEntity,
    BillingPaymentEntity,
)
from core_api.modules.billing.billing_errors import (
    BillingConflictError,
    BillingNotFoundError,
    BillingProviderError,
)
from core_api.modules.billing.billing_schema import (
    BillingPaymentRead,
    BillingPlanRead,
    BillingSubscriptionRead,
    CheckoutCreate,
    CheckoutRead,
    MercadoPagoWebhookPayload,
    PublicCheckoutCreate,
    PublicCheckoutStatusRead,
    WebhookRead,
)
from core_api.modules.billing.providers.base import CheckoutRequest
from core_api.modules.billing.providers.factory import billing_provider
from core_api.modules.plans.plan_entity import PlanEntity
from core_api.modules.staff_profiles.staff_profile_entity import StaffProfileEntity
from core_api.modules.subscriptions.subscription_entity import SubscriptionEntity
from core_api.modules.tenants.tenant_entity import TenantEntity
from core_api.shared.auth.context import RequestContext
from shared_kernel.identifiers import Identifier
from shared_kernel.time.datetime_service import DateTimeService

_SUBSCRIPTION_STATUSES = {
    "pending": "pending",
    "authorized": "active",
    "paused": "past_due",
    "cancelled": "cancelled",
}
_PAYMENT_STATUSES = {
    "approved": "confirmed",
    "authorized": "confirmed",
    "pending": "pending",
    "in_process": "pending",
    "rejected": "failed",
    "cancelled": "failed",
    "refunded": "refunded",
    "charged_back": "refunded",
}


def _slug(value: str, suffix: str) -> str:
    normalized = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    )
    token = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "empresa"
    return f"{token[:60]}-{suffix}"


class BillingService:
    def __init__(
        self,
        session_factory: sessionmaker = SessionLocal,
        provider_factory=billing_provider,
        auth_client=auth_provisioning_client,
    ) -> None:
        self.session_factory = session_factory
        self.provider_factory = provider_factory
        self.auth_client = auth_client

    @staticmethod
    def _tenant_id(context: RequestContext) -> Identifier:
        if context.tenant_id is None:
            raise BillingConflictError("An active workspace is required")
        return context.tenant_id

    @staticmethod
    def _valid_key(value: str) -> str:
        key = value.strip()
        if not key or len(key) > 120:
            raise BillingConflictError("A valid Idempotency-Key is required")
        return key

    @staticmethod
    def _plan(session: Session, plan_id: Identifier) -> PlanEntity:
        plan = session.scalar(
            select(PlanEntity).where(
                PlanEntity.id == plan_id,
                PlanEntity.active.is_(True),
                PlanEntity.price_cents > 0,
                PlanEntity.deleted_at.is_(None),
            )
        )
        if plan is None:
            raise BillingNotFoundError("Active billing plan not found")
        return plan

    def list_plans(self) -> list[BillingPlanRead]:
        with self.session_factory() as session:
            plans = session.scalars(
                select(PlanEntity)
                .where(
                    PlanEntity.active.is_(True),
                    PlanEntity.price_cents > 0,
                    PlanEntity.deleted_at.is_(None),
                )
                .order_by(PlanEntity.price_cents, PlanEntity.name)
            ).all()
            return [BillingPlanRead.model_validate(item) for item in plans]

    def current_subscription(
        self, context: RequestContext
    ) -> BillingSubscriptionRead | None:
        tenant_id = self._tenant_id(context)
        with self.session_factory() as session:
            item = session.scalar(
                select(SubscriptionEntity)
                .where(
                    SubscriptionEntity.tenant_id == tenant_id,
                    SubscriptionEntity.deleted_at.is_(None),
                )
                .order_by(SubscriptionEntity.created_at.desc())
            )
            return (
                BillingSubscriptionRead.model_validate(item, from_attributes=True)
                if item
                else None
            )

    def list_payments(self, context: RequestContext) -> list[BillingPaymentRead]:
        tenant_id = self._tenant_id(context)
        with self.session_factory() as session:
            items = session.scalars(
                select(BillingPaymentEntity)
                .where(
                    BillingPaymentEntity.tenant_id == tenant_id,
                    BillingPaymentEntity.deleted_at.is_(None),
                )
                .order_by(BillingPaymentEntity.created_at.desc())
            ).all()
            return [
                BillingPaymentRead.model_validate(item, from_attributes=True)
                for item in items
            ]

    def _provider_checkout(
        self,
        checkout_id: Identifier,
        plan: PlanEntity,
        payer_email: str,
        key: str,
        back_path: str,
    ) -> CheckoutRead:
        provider = self.provider_factory()
        base_url = settings.BILLING_PUBLIC_BASE_URL.rstrip("/")
        try:
            result = provider.create_checkout(
                CheckoutRequest(
                    reason=plan.name,
                    external_reference=str(checkout_id),
                    payer_email=payer_email,
                    amount_cents=plan.price_cents,
                    currency=plan.currency,
                    interval=plan.billing_interval,
                    back_url=f"{base_url}{back_path}",
                    notification_url=f"{base_url}/core/webhooks/billing/mercado-pago",
                    idempotency_key=key,
                )
            )
        except Exception:
            with self.session_factory() as session:
                failed = session.get(BillingCheckoutSessionEntity, checkout_id)
                if failed is not None:
                    failed.status = "failed"
                    session.commit()
            raise
        with self.session_factory() as session:
            checkout = session.get(BillingCheckoutSessionEntity, checkout_id)
            if checkout is None:
                raise BillingNotFoundError(
                    "Checkout disappeared during provider creation"
                )
            checkout.provider = provider.name
            checkout.provider_checkout_id = result.provider_id
            checkout.checkout_url = result.checkout_url
            checkout.status = result.status
            if checkout.subscription_id:
                subscription = session.get(SubscriptionEntity, checkout.subscription_id)
                if subscription is not None:
                    subscription.provider = provider.name
                    subscription.provider_subscription_id = result.provider_id
            session.commit()
            session.refresh(checkout)
            return CheckoutRead.model_validate(checkout, from_attributes=True)

    def create_checkout(
        self, context: RequestContext, payload: CheckoutCreate, idempotency_key: str
    ) -> CheckoutRead:
        tenant_id = self._tenant_id(context)
        key = self._valid_key(idempotency_key)
        with self.session_factory() as session:
            existing = session.scalar(
                select(BillingCheckoutSessionEntity).where(
                    BillingCheckoutSessionEntity.tenant_id == tenant_id,
                    BillingCheckoutSessionEntity.idempotency_key == key,
                )
            )
            if existing is not None:
                return CheckoutRead.model_validate(existing, from_attributes=True)
            plan = self._plan(session, payload.plan_id)
            subscription = SubscriptionEntity(
                tenant_id=tenant_id,
                plan_id=plan.id,
                name=plan.name,
                code=f"billing-{str(tenant_id).replace('-', '')[:12]}-{hashlib.sha256(key.encode()).hexdigest()[:16]}",
                provider=settings.BILLING_PROVIDER,
                status="pending",
            )
            session.add(subscription)
            session.flush()
            checkout = BillingCheckoutSessionEntity(
                tenant_id=tenant_id,
                plan_id=plan.id,
                subscription_id=subscription.id,
                provider=settings.BILLING_PROVIDER,
                status="pending",
                payer_email=payload.payer_email,
                idempotency_key=key,
                provisioning_status="not_required",
            )
            session.add(checkout)
            session.commit()
            session.refresh(checkout)
            checkout_id, detached_plan = checkout.id, plan
            session.expunge(detached_plan)
        return self._provider_checkout(
            checkout_id, detached_plan, payload.payer_email, key, "/settings/billing"
        )

    def create_public_checkout(
        self, payload: PublicCheckoutCreate, idempotency_key: str
    ) -> CheckoutRead:
        key = self._valid_key(idempotency_key)
        with self.session_factory() as session:
            existing = session.scalar(
                select(BillingCheckoutSessionEntity).where(
                    BillingCheckoutSessionEntity.payer_email == payload.payer_email,
                    BillingCheckoutSessionEntity.idempotency_key == key,
                )
            )
            if existing is not None:
                return CheckoutRead.model_validate(existing, from_attributes=True)
            if (
                session.scalar(
                    select(TenantEntity.id).where(
                        TenantEntity.document == payload.document,
                        TenantEntity.deleted_at.is_(None),
                    )
                )
                is not None
            ):
                raise BillingConflictError("This company already has a Nexo workspace")
            plan = self._plan(session, payload.plan_id)
            checkout = BillingCheckoutSessionEntity(
                plan_id=plan.id,
                provider=settings.BILLING_PROVIDER,
                status="pending",
                payer_email=payload.payer_email,
                idempotency_key=key,
                company_name=payload.company_name,
                legal_name=payload.legal_name,
                document=payload.document,
                phone=payload.phone,
                admin_name=payload.admin_name,
                provisioning_status="awaiting_payment",
            )
            session.add(checkout)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                replay = session.scalar(
                    select(BillingCheckoutSessionEntity).where(
                        BillingCheckoutSessionEntity.payer_email == payload.payer_email,
                        BillingCheckoutSessionEntity.idempotency_key == key,
                    )
                )
                if replay is not None:
                    return CheckoutRead.model_validate(replay, from_attributes=True)
                raise BillingConflictError("Checkout could not be created") from exc
            session.refresh(checkout)
            checkout_id, detached_plan = checkout.id, plan
            session.expunge(detached_plan)
        return self._provider_checkout(
            checkout_id, detached_plan, payload.payer_email, key, "/subscribe"
        )

    def public_checkout_status(
        self, checkout_id: Identifier
    ) -> PublicCheckoutStatusRead:
        with self.session_factory() as session:
            checkout = session.get(BillingCheckoutSessionEntity, checkout_id)
            if checkout is None or checkout.company_name is None:
                raise BillingNotFoundError("Checkout not found")
            return PublicCheckoutStatusRead.model_validate(
                checkout, from_attributes=True
            )

    def cancel(self, context: RequestContext) -> BillingSubscriptionRead:
        tenant_id = self._tenant_id(context)
        with self.session_factory() as session:
            subscription = session.scalar(
                select(SubscriptionEntity)
                .where(
                    SubscriptionEntity.tenant_id == tenant_id,
                    SubscriptionEntity.status.in_(("pending", "active", "past_due")),
                    SubscriptionEntity.deleted_at.is_(None),
                )
                .order_by(SubscriptionEntity.created_at.desc())
            )
            if subscription is None:
                raise BillingNotFoundError("Active subscription not found")
            provider_id, subscription_id = (
                subscription.provider_subscription_id,
                subscription.id,
            )
        if not provider_id:
            raise BillingConflictError(
                "Subscription is not linked to the payment provider"
            )
        result = self.provider_factory().cancel_subscription(provider_id)
        if str(result.get("status")) != "cancelled":
            raise BillingProviderError("Provider did not confirm cancellation")
        with self.session_factory() as session:
            subscription = session.get(SubscriptionEntity, subscription_id)
            if subscription is None or subscription.tenant_id != tenant_id:
                raise BillingNotFoundError("Subscription not found")
            subscription.status = "cancelled"
            session.commit()
            session.refresh(subscription)
            return BillingSubscriptionRead.model_validate(
                subscription, from_attributes=True
            )

    @staticmethod
    def _payload_hash(payload: MercadoPagoWebhookPayload) -> str:
        encoded = json.dumps(
            payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _checkout_from_external_reference(
        session: Session, value: object
    ) -> BillingCheckoutSessionEntity:
        try:
            checkout_id = UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise BillingNotFoundError("Webhook has no valid Nexo reference") from exc
        checkout = session.get(BillingCheckoutSessionEntity, checkout_id)
        if checkout is None:
            raise BillingNotFoundError("Webhook checkout reference was not found")
        return checkout

    def _prepare_public_purchase(self, checkout_id: Identifier) -> None:
        with self.session_factory() as session:
            checkout = session.get(BillingCheckoutSessionEntity, checkout_id)
            if (
                checkout is None
                or checkout.company_name is None
                or checkout.legal_name is None
                or checkout.document is None
            ):
                return
            if checkout.tenant_id and checkout.subscription_id:
                return
            if (
                session.scalar(
                    select(TenantEntity.id).where(
                        TenantEntity.document == checkout.document,
                        TenantEntity.deleted_at.is_(None),
                    )
                )
                is not None
            ):
                checkout.provisioning_status = "conflict"
                session.commit()
                raise BillingConflictError(
                    "Company document already belongs to another workspace"
                )
            tenant = TenantEntity(
                legal_name=checkout.legal_name,
                trade_name=checkout.company_name,
                slug=_slug(
                    checkout.company_name, str(checkout.id).replace("-", "")[:8]
                ),
                document=checkout.document,
                status="active",
            )
            session.add(tenant)
            session.flush()
            subscription = SubscriptionEntity(
                tenant_id=tenant.id,
                plan_id=checkout.plan_id,
                name="Nexo Bot",
                code=f"billing-{str(tenant.id).replace('-', '')[:12]}-{str(checkout.id).replace('-', '')[:16]}",
                provider=checkout.provider,
                provider_subscription_id=checkout.provider_checkout_id,
                status="pending",
            )
            session.add(subscription)
            session.flush()
            checkout.tenant_id = tenant.id
            checkout.subscription_id = subscription.id
            checkout.provisioning_status = "creating_admin"
            session.commit()

    def _ensure_public_admin(self, checkout_id: Identifier) -> None:
        with self.session_factory() as session:
            checkout = session.get(BillingCheckoutSessionEntity, checkout_id)
            if (
                checkout is None
                or checkout.company_name is None
                or checkout.tenant_id is None
            ):
                return
            auth_user_id = checkout.auth_user_id
            email, admin_name, tenant_id = (
                checkout.payer_email,
                checkout.admin_name or checkout.payer_email,
                checkout.tenant_id,
            )
        if auth_user_id is None:
            auth_user_id = self.auth_client.provision_admin(email)
            with self.session_factory() as session:
                checkout = session.get(BillingCheckoutSessionEntity, checkout_id)
                if checkout is None:
                    raise BillingNotFoundError("Checkout not found during provisioning")
                checkout.auth_user_id = auth_user_id
                session.commit()
        with self.session_factory() as session:
            existing = session.scalar(
                select(StaffProfileEntity).where(
                    StaffProfileEntity.tenant_id == tenant_id,
                    StaffProfileEntity.auth_user_id == auth_user_id,
                )
            )
            if existing is None:
                session.add(
                    StaffProfileEntity(
                        tenant_id=tenant_id,
                        auth_user_id=auth_user_id,
                        display_name=admin_name,
                        code=f"owner-{str(checkout_id).replace('-', '')[:12]}",
                        status="active",
                        available=False,
                        max_concurrent_conversations=10,
                    )
                )
            checkout = session.get(BillingCheckoutSessionEntity, checkout_id)
            if checkout is not None:
                checkout.provisioning_status = "completed"
            session.commit()

    def process_mercado_pago_webhook(
        self,
        *,
        payload: MercadoPagoWebhookPayload,
        data_id: str,
        x_signature: str | None,
        x_request_id: str | None,
    ) -> WebhookRead:
        provider = self.provider_factory()
        validate = getattr(provider, "validate_webhook_signature", None)
        if provider.name == "mercado_pago":
            if validate is None:
                raise BillingProviderError("Provider cannot validate webhooks")
            validate(
                x_signature=x_signature, x_request_id=x_request_id, data_id=data_id
            )
        event_id = f"{payload.type}:{data_id}:{payload.action or ''}"
        with self.session_factory() as session:
            if (
                session.scalar(
                    select(BillingEventEntity.id).where(
                        BillingEventEntity.provider == provider.name,
                        BillingEventEntity.provider_event_id == event_id,
                    )
                )
                is not None
            ):
                return WebhookRead(duplicate=True)
        if payload.type == "payment":
            resource = provider.get_payment(data_id)
        elif payload.type == "subscription_preapproval":
            resource = provider.get_subscription(data_id)
        else:
            resource = {"id": data_id, "external_reference": None, "status": "ignored"}
        checkout_id: Identifier | None = None
        if payload.type in {"payment", "subscription_preapproval"}:
            with self.session_factory() as session:
                checkout = self._checkout_from_external_reference(
                    session, resource.get("external_reference")
                )
                checkout_id = checkout.id
            if (
                payload.type == "payment"
                and _PAYMENT_STATUSES.get(str(resource.get("status") or "pending"))
                == "confirmed"
            ):
                self._prepare_public_purchase(checkout_id)
                self._ensure_public_admin(checkout_id)
        with self.session_factory() as session:
            event = BillingEventEntity(
                provider=provider.name,
                provider_event_id=event_id,
                event_type=payload.type,
                action=payload.action,
                resource_id=data_id,
                payload_hash=self._payload_hash(payload),
                status="received",
            )
            session.add(event)
            if payload.type in {"payment", "subscription_preapproval"}:
                checkout = self._checkout_from_external_reference(
                    session, resource.get("external_reference")
                )
                subscription = (
                    session.get(SubscriptionEntity, checkout.subscription_id)
                    if checkout.subscription_id
                    else None
                )
                if payload.type == "subscription_preapproval":
                    provider_status = str(resource.get("status") or "pending")
                    if subscription is not None:
                        subscription.status = _SUBSCRIPTION_STATUSES.get(
                            provider_status, "pending"
                        )
                        subscription.provider_subscription_id = str(
                            resource.get("id") or data_id
                        )
                    checkout.status = (
                        "completed"
                        if subscription and subscription.status == "active"
                        else provider_status
                    )
                elif subscription is not None and checkout.tenant_id is not None:
                    provider_status = str(resource.get("status") or "pending")
                    status = _PAYMENT_STATUSES.get(provider_status, "pending")
                    amount = Decimal(str(resource.get("transaction_amount") or "0"))
                    amount_cents = int(
                        (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                    )
                    payment = session.scalar(
                        select(BillingPaymentEntity).where(
                            BillingPaymentEntity.provider == provider.name,
                            BillingPaymentEntity.provider_payment_id == data_id,
                        )
                    )
                    if payment is None:
                        payment = BillingPaymentEntity(
                            tenant_id=checkout.tenant_id,
                            subscription_id=subscription.id,
                            provider=provider.name,
                            provider_payment_id=data_id,
                            status=status,
                            amount_cents=amount_cents,
                            currency=str(resource.get("currency_id") or "BRL"),
                        )
                        session.add(payment)
                    else:
                        payment.status, payment.amount_cents = status, amount_cents
                    if status == "confirmed":
                        payment.paid_at = DateTimeService.utc_now()
                        subscription.status, checkout.status = "active", "completed"
                    elif status == "failed" and subscription.status != "active":
                        subscription.status = "past_due"
                    elif status == "refunded":
                        subscription.status = "cancelled"
                event.status = "processed"
            else:
                event.status = "ignored"
            event.processed_at = DateTimeService.utc_now()
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return WebhookRead(duplicate=True)
        return WebhookRead()


billing_service = BillingService()
