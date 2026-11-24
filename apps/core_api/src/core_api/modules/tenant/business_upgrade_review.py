from datetime import datetime
from typing import Literal
from secrets import token_urlsafe
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, String, Uuid, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from core_api.infrastructure.database.connection import BaseEntity, SessionLocal
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_identity import InvalidBusinessIdentifierError, protect_cnpj
from core_api.modules.tenant.tenant_schema import TenantBusinessConversion
from core_api.modules.tenant.tenant_service import billing_currency_for_country, tenant_service
from shared_kernel.time.datetime_service import DateTimeService


class BusinessUpgradeReviewEntity(BaseEntity):
    __tablename__ = "business_upgrade_reviews"

    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), unique=True)
    business_tenant_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"), unique=True)
    requested_by: Mapped[str] = mapped_column(String(255))
    legal_name: Mapped[str] = mapped_column(String(240))
    cnpj_encrypted: Mapped[str] = mapped_column(String(512))
    cnpj_lookup: Mapped[str] = mapped_column(String(64))
    cnpj_masked: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BusinessUpgradeReviewRead(BaseModel):
    id: UUID
    legal_name: str
    cnpj_masked: str
    status: Literal["pending", "approved", "rejected"]


def request_review(
    tenant_id: UUID, payload: TenantBusinessConversion, subject: str
) -> BusinessUpgradeReviewRead:
    with SessionLocal.begin() as db:
        tenant_service.require_role(db, tenant_id, subject, {"admin"}, allow_over_limit=True)
        tenant = db.scalar(select(TenantEntity).where(
            TenantEntity.id == tenant_id, TenantEntity.deleted_at.is_(None)
        ).with_for_update())
        if tenant is None or tenant.kind != "personal":
            raise WorkflowError("Request a new business workspace from your personal workspace", 409)
        try:
            encrypted, lookup, masked = protect_cnpj(payload.cnpj)
        except InvalidBusinessIdentifierError as exc:
            raise WorkflowError(str(exc), 422) from exc
        if db.scalar(select(TenantEntity.id).where(
            TenantEntity.registration_lookup_hmac == lookup, TenantEntity.deleted_at.is_(None)
        ).limit(1)) is not None:
            raise WorkflowError("Request access from the administrator of the existing business workspace", 409)
        review = db.scalar(select(BusinessUpgradeReviewEntity).where(
            BusinessUpgradeReviewEntity.tenant_id == tenant_id
        ).with_for_update())
        name = payload.legal_name.strip()
        if review is not None and review.status != "rejected":
            if review.cnpj_lookup != lookup or review.legal_name != name:
                raise WorkflowError("A different business review is already open", 409)
            return BusinessUpgradeReviewRead.model_validate(review, from_attributes=True)
        if review is None:
            review = BusinessUpgradeReviewEntity(tenant_id=tenant_id)
            db.add(review)
        review.requested_by = subject.strip().lower()
        review.legal_name = name
        review.cnpj_encrypted = encrypted
        review.cnpj_lookup = lookup
        review.cnpj_masked = masked
        review.status = "pending"
        review.reviewed_by = None
        review.reviewed_at = None
        db.flush()
        tenant_service._audit(db, tenant_id, subject, "tenant.business_upgrade_requested", {
            "review_id": str(review.id),
        })
        return BusinessUpgradeReviewRead.model_validate(review, from_attributes=True)


def read_review(tenant_id: UUID, subject: str) -> BusinessUpgradeReviewRead | None:
    with SessionLocal() as db:
        tenant_service.require_role(db, tenant_id, subject, {"admin"}, allow_over_limit=True)
        review = db.scalar(select(BusinessUpgradeReviewEntity).where(
            BusinessUpgradeReviewEntity.tenant_id == tenant_id,
            BusinessUpgradeReviewEntity.requested_by == subject.strip().lower(),
        ))
        return BusinessUpgradeReviewRead.model_validate(review, from_attributes=True) if review else None


def record_decision(review_id: UUID, decision: Literal["approved", "rejected"], operator: str) -> None:
    try:
        with SessionLocal.begin() as db:
            review = db.scalar(select(BusinessUpgradeReviewEntity).where(
                BusinessUpgradeReviewEntity.id == review_id
            ).with_for_update())
            if review is None or review.status != "pending":
                raise WorkflowError("Pending business review was not found", 404)
            if decision == "approved" and db.scalar(select(TenantEntity.id).where(
                TenantEntity.registration_lookup_hmac == review.cnpj_lookup,
                TenantEntity.deleted_at.is_(None),
            ).limit(1)) is not None:
                raise WorkflowError("The CNPJ already belongs to a business workspace", 409)
            review.status = decision
            review.reviewed_by = operator
            review.reviewed_at = DateTimeService.utc_now()
            tenant_service._audit(db, review.tenant_id, operator, "tenant.business_upgrade_reviewed", {
                "review_id": str(review.id), "decision": decision,
            })
    except IntegrityError as exc:
        raise WorkflowError("The CNPJ already has an approved business review", 409) from exc


def prepare_business_checkout(source_id: UUID, subject: str) -> UUID:
    with SessionLocal.begin() as db:
        actor = tenant_service.require_role(db, source_id, subject, {"admin"}, allow_over_limit=True)
        source = db.get(TenantEntity, source_id, with_for_update=True)
        if source is None or source.deleted_at is not None:
            raise WorkflowError("Workspace not found", 404)
        if source.kind == "business":
            return source.id
        review = db.scalar(select(BusinessUpgradeReviewEntity).where(
            BusinessUpgradeReviewEntity.tenant_id == source_id
        ).with_for_update())
        if review is None or review.status != "approved" or review.requested_by != subject.strip().lower():
            raise WorkflowError(
                "The business registration must be approved before checkout",
                409,
                code="business_review_required",
            )
        if review.business_tenant_id is not None:
            existing = db.get(TenantEntity, review.business_tenant_id)
            if existing is None or existing.deleted_at is not None:
                raise WorkflowError("The approved workspace needs operator review", 409)
            if existing.status != "pending_billing":
                raise WorkflowError("Use the business workspace to manage this subscription", 409)
            return existing.id
        if not source.country_code:
            raise WorkflowError("Set the workspace country before opening checkout", 409)
        if db.scalar(select(TenantEntity.id).where(
            TenantEntity.registration_lookup_hmac == review.cnpj_lookup,
            TenantEntity.deleted_at.is_(None),
        ).limit(1)) is not None:
            raise WorkflowError("Request access from the administrator of the existing business workspace", 409)
        business = TenantEntity(
            name=review.legal_name[:160],
            legal_name=review.legal_name,
            slug=token_urlsafe(18),
            status="pending_billing",
            kind="business",
            country_code=source.country_code,
            default_locale=source.default_locale,
            timezone=source.timezone,
            currency=billing_currency_for_country(source.country_code),
            registration_country="BR",
            registration_type="BR_CNPJ",
            registration_value_encrypted=review.cnpj_encrypted,
            registration_lookup_hmac=review.cnpj_lookup,
            registration_masked=review.cnpj_masked,
            registration_verification_status="format_valid",
            registration_source="manual_review",
        )
        db.add(business)
        db.flush()
        db.add(TenantMemberEntity(
            tenant_id=business.id,
            auth_user_id=subject.strip().lower(),
            auth_user_uuid=actor.auth_user_uuid,
            role="admin",
            status="pending",
        ))
        db.add(BillingAccountEntity(tenant_id=business.id, status="not_configured"))
        review.business_tenant_id = business.id
        tenant_service._audit(db, business.id, subject, "tenant.business_checkout_prepared", {
            "review_id": str(review.id),
        })
        return business.id


def activate_paid_business_workspace(db, tenant_id: UUID) -> None:
    business = db.get(TenantEntity, tenant_id, with_for_update=True)
    if business is None or business.status != "pending_billing" or business.deleted_at is not None:
        return
    member = db.scalar(select(TenantMemberEntity).where(
        TenantMemberEntity.tenant_id == tenant_id,
        TenantMemberEntity.role == "admin",
        TenantMemberEntity.status == "pending",
        TenantMemberEntity.deleted_at.is_(None),
    ).with_for_update())
    if member is None:
        raise WorkflowError("Pending business administrator was not found", 500)
    business.status = "active"
    member.status = "active"
    member.joined_at = DateTimeService.utc_now()
    tenant_service._audit(db, tenant_id, "stripe", "tenant.business_workspace_activated", {})
