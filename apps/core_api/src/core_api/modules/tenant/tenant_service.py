from secrets import token_urlsafe

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from uuid import UUID, uuid4

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.auth_context import active_auth_context
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.signature_request.signature_request_entity import AuditEventEntity
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_identity import InvalidBusinessIdentifierError, protect_cnpj
from core_api.modules.tenant.user_client import resolve_auth_user
from shared_kernel.time.datetime_service import DateTimeService
from core_api.modules.tenant.tenant_schema import (
    TenantBusinessConversion,
    TenantCreate,
    TenantMemberCreate,
    TenantMemberRead,
    TenantProvision,
    TenantPreferencesUpdate,
    TenantRead,
)

EURO_COUNTRY_CODES = frozenset(
    {
        "AD", "AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR",
        "IE", "IT", "LT", "LU", "LV", "MC", "ME", "MT", "NL", "PT", "SI",
        "SK", "SM", "VA", "XK",
    }
)


def _public_slug() -> str:
    """Return an opaque, URL-safe identifier with 144 bits of entropy."""
    return token_urlsafe(18)


def billing_currency_for_country(country_code: str | None) -> str:
    code = (country_code or "").upper()
    if code == "BR":
        return "BRL"
    if code == "JP":
        return "JPY"
    if code in EURO_COUNTRY_CODES:
        return "EUR"
    return "USD"


class TenantService:
    def provision_owner(self, payload: TenantProvision) -> TenantRead:
        owner = payload.owner_email.strip().lower()
        with SessionLocal.begin() as db:
            existing = db.execute(
                select(TenantEntity, TenantMemberEntity.role)
                .join(TenantMemberEntity, TenantMemberEntity.tenant_id == TenantEntity.id)
                .where(
                    self.membership_identity_filter(owner, payload.owner_user_id),
                    TenantMemberEntity.role == "admin",
                    TenantEntity.deleted_at.is_(None),
                )
                .order_by(TenantEntity.created_at)
            ).first()
            if existing is not None:
                member = db.scalar(
                    select(TenantMemberEntity).where(
                        TenantMemberEntity.tenant_id == existing[0].id,
                        self.membership_identity_filter(owner, payload.owner_user_id),
                    )
                )
                if member is not None and member.auth_user_uuid is None:
                    member.auth_user_uuid = payload.owner_user_id
                    db.flush()
                return self._read(existing[0], existing[1])

            tenant = TenantEntity(
                name=payload.name.strip(),
                slug=_public_slug(),
                status="active",
                default_locale=payload.default_locale,
                country_code=payload.country_code,
                timezone="UTC",
                currency=billing_currency_for_country(payload.country_code),
            )
            db.add(tenant)
            db.flush()
            db.add(
                TenantMemberEntity(
                    tenant_id=tenant.id,
                    auth_user_id=owner,
                    auth_user_uuid=payload.owner_user_id,
                    role="admin",
                    status="active",
                    joined_at=DateTimeService.utc_now(),
                )
            )
            db.add(BillingAccountEntity(tenant_id=tenant.id, status="not_configured"))
            db.flush()
            return self._read(tenant, "admin")

    def list_for(self, subject: str) -> list[TenantRead]:
        with SessionLocal() as db:
            rows = db.execute(
                select(TenantEntity, TenantMemberEntity.role)
                .join(TenantMemberEntity, TenantMemberEntity.tenant_id == TenantEntity.id)
                .where(self.membership_identity_filter(subject), TenantEntity.deleted_at.is_(None))
                .order_by(TenantEntity.name)
            ).all()
            return [self._read(tenant, role) for tenant, role in rows]

    def create(self, payload: TenantCreate, subject: str) -> TenantRead:
        with SessionLocal.begin() as db:
            tenant = TenantEntity(
                name=payload.name.strip(),
                slug=_public_slug(),
                status="active",
                default_locale=payload.default_locale,
                country_code=payload.country_code,
                timezone=payload.timezone,
                currency=payload.currency,
            )
            db.add(tenant)
            try:
                db.flush()
            except IntegrityError as exc:
                raise WorkflowError("Tenant slug is already in use", 409) from exc
            member = TenantMemberEntity(tenant_id=tenant.id, auth_user_id=subject.lower(), role="admin")
            db.add(member)
            db.add(BillingAccountEntity(tenant_id=tenant.id, status="not_configured"))
            db.flush()
            return self._read(tenant, "admin")

    def add_member(self, tenant_id: UUID, payload: TenantMemberCreate, subject: str) -> None:
        with SessionLocal.begin() as db:
            self.require_role(db, tenant_id, subject, {"admin"})
            tenant = db.get(TenantEntity, tenant_id)
            if tenant is None or tenant.deleted_at is not None:
                raise WorkflowError("Tenant not found", 404)
            if tenant.kind != "business":
                raise WorkflowError("Additional members require a business tenant", 409)
            from core_api.modules.billing.billing_service import billing_service

            if not billing_service.business_features_enabled(db, tenant_id):
                raise WorkflowError("A Professional plan is required for business members", 403)
            active_members = db.scalar(
                select(func.count(TenantMemberEntity.id)).where(
                    TenantMemberEntity.tenant_id == tenant_id,
                    TenantMemberEntity.deleted_at.is_(None),
                    TenantMemberEntity.status == "active",
                )
            ) or 0
            if active_members >= 3:
                raise WorkflowError("The Professional plan allows up to 3 tenant members", 409)
            member_user_uuid = resolve_auth_user(payload.auth_user_id.lower())
            db.add(TenantMemberEntity(tenant_id=tenant_id, auth_user_id=payload.auth_user_id.lower(), auth_user_uuid=member_user_uuid, role=payload.role, status="active", joined_at=DateTimeService.utc_now()))
            try:
                db.flush()
            except IntegrityError as exc:
                raise WorkflowError("User is already a tenant member", 409) from exc
            self._audit(db, tenant_id, subject, "tenant.member_added", {"member_role": payload.role, "member_count": active_members + 1})

    def list_members(self, tenant_id: UUID, subject: str) -> list[TenantMemberRead]:
        with SessionLocal() as db:
            self.require_role(db, tenant_id, subject, {"admin", "auditor"})
            members = db.scalars(
                select(TenantMemberEntity)
                .where(
                    TenantMemberEntity.tenant_id == tenant_id,
                    TenantMemberEntity.deleted_at.is_(None),
                )
                .order_by(TenantMemberEntity.joined_at, TenantMemberEntity.created_at)
            ).all()
            return [
                TenantMemberRead.model_validate(member, from_attributes=True)
                for member in members
            ]

    def convert_to_business(
        self,
        tenant_id: UUID,
        payload: TenantBusinessConversion,
        subject: str,
    ) -> TenantRead:
        with SessionLocal.begin() as db:
            member = self.require_role(db, tenant_id, subject, {"admin"})
            tenant = db.scalar(
                select(TenantEntity)
                .where(TenantEntity.id == tenant_id, TenantEntity.deleted_at.is_(None))
                .with_for_update()
            )
            if tenant is None:
                raise WorkflowError("Tenant not found", 404)
            if tenant.kind == "business":
                raise WorkflowError("Tenant is already a business tenant", 409)
            from core_api.modules.billing.billing_service import billing_service

            if not billing_service.business_features_enabled(db, tenant_id):
                raise WorkflowError("A Professional plan is required for a business tenant", 403)
            account = db.scalar(
                select(BillingAccountEntity).where(
                    BillingAccountEntity.tenant_id == tenant_id,
                    BillingAccountEntity.deleted_at.is_(None),
                )
            )
            if account is None or not account.complimentary_lifetime:
                raise WorkflowError(
                    "Business identity is collected by Stripe during the Professional upgrade",
                    409,
                )
            try:
                encrypted, lookup, masked = protect_cnpj(payload.cnpj)
            except InvalidBusinessIdentifierError as exc:
                raise WorkflowError(str(exc), 422) from exc
            conflict = db.scalar(
                select(TenantEntity.id).where(
                    TenantEntity.registration_lookup_hmac == lookup,
                    TenantEntity.deleted_at.is_(None),
                    TenantEntity.id != tenant_id,
                )
            )
            if conflict is not None:
                raise WorkflowError("This CNPJ is already associated with another tenant", 409)
            tenant.kind = "business"
            tenant.name = payload.legal_name.strip()
            tenant.legal_name = payload.legal_name.strip()
            tenant.registration_country = "BR"
            tenant.registration_type = "BR_CNPJ"
            tenant.registration_value_encrypted = encrypted
            tenant.registration_lookup_hmac = lookup
            tenant.registration_masked = masked
            tenant.registration_verification_status = "format_valid"
            db.flush()
            self._audit(db, tenant.id, subject, "tenant.converted_to_business", {"registration_country": "BR", "registration_type": "BR_CNPJ", "registration_masked": masked, "verification_status": "format_valid"})
            return self._read(tenant, member.role)

    def apply_billing_business_identity(
        self,
        db,
        tenant_id: UUID,
        *,
        legal_name: str | None,
        cnpj: str | None,
        provider_reference: str | None,
    ) -> str:
        tenant = db.scalar(
            select(TenantEntity)
            .where(
                TenantEntity.id == tenant_id,
                TenantEntity.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if tenant is None:
            raise WorkflowError("Tenant not found", 404)
        tenant.registration_source = "stripe"
        tenant.registration_provider_reference = provider_reference
        if not cnpj:
            tenant.registration_verification_status = "stripe_cnpj_required"
            return tenant.registration_verification_status
        try:
            encrypted, lookup, masked = protect_cnpj(cnpj)
        except InvalidBusinessIdentifierError:
            tenant.registration_verification_status = "stripe_cnpj_invalid"
            return tenant.registration_verification_status
        if tenant.kind == "business" and tenant.registration_lookup_hmac != lookup:
            tenant.registration_verification_status = "stripe_cnpj_mismatch"
            return tenant.registration_verification_status
        conflict = db.scalar(
            select(TenantEntity.id).where(
                TenantEntity.registration_lookup_hmac == lookup,
                TenantEntity.deleted_at.is_(None),
                TenantEntity.id != tenant_id,
            )
        )
        if conflict is not None:
            tenant.registration_verification_status = "stripe_cnpj_conflict"
            return tenant.registration_verification_status
        normalized_name = (legal_name or "").strip()
        if not normalized_name:
            tenant.registration_verification_status = "stripe_name_required"
            return tenant.registration_verification_status
        was_personal = tenant.kind == "personal"
        tenant.kind = "business"
        tenant.name = normalized_name
        tenant.legal_name = normalized_name
        tenant.registration_country = "BR"
        tenant.registration_type = "BR_CNPJ"
        tenant.registration_value_encrypted = encrypted
        tenant.registration_lookup_hmac = lookup
        tenant.registration_masked = masked
        tenant.registration_verification_status = "stripe_format_valid"
        if was_personal:
            self._audit(
                db,
                tenant.id,
                "stripe",
                "tenant.converted_to_business_from_billing",
                {
                    "registration_country": "BR",
                    "registration_type": "BR_CNPJ",
                    "registration_masked": masked,
                    "verification_status": tenant.registration_verification_status,
                    "provider_reference": provider_reference,
                },
            )
        return tenant.registration_verification_status

    @staticmethod
    def issuer_snapshot(tenant: TenantEntity) -> dict[str, object]:
        return {
            "tenant_id": str(tenant.id),
            "tenant_kind": tenant.kind,
            "display_name": tenant.name,
            "legal_name": tenant.legal_name,
            "registration_country": tenant.registration_country,
            "registration_type": tenant.registration_type,
            "registration_masked": tenant.registration_masked,
            "registration_verification_status": tenant.registration_verification_status,
        }

    def update_preferences(
        self,
        tenant_id: UUID,
        payload: TenantPreferencesUpdate,
        subject: str,
    ) -> TenantRead:
        with SessionLocal.begin() as db:
            member = self.require_role(db, tenant_id, subject, {"admin"})
            tenant = db.get(TenantEntity, tenant_id)
            if tenant is None or tenant.deleted_at is not None:
                raise WorkflowError("Tenant not found", 404)
            tenant.default_locale = payload.default_locale
            tenant.country_code = payload.country_code
            tenant.timezone = payload.timezone
            tenant.currency = payload.currency
            db.flush()
            return self._read(tenant, member.role)

    @staticmethod
    def require_role(db, tenant_id: UUID, subject: str, roles: set[str] | None = None) -> TenantMemberEntity:
        member = db.scalar(select(TenantMemberEntity).where(TenantMemberEntity.tenant_id == tenant_id, TenantService.membership_identity_filter(subject), TenantMemberEntity.deleted_at.is_(None), TenantMemberEntity.status == "active"))
        if member is None or (roles is not None and member.role not in roles):
            raise WorkflowError("Tenant access denied", 403)
        return member

    @staticmethod
    def membership_identity_filter(subject: str, user_id: UUID | None = None):
        context = active_auth_context()
        resolved_user_id = user_id
        if resolved_user_id is None and context is not None and context.user_id:
            try:
                resolved_user_id = UUID(context.user_id)
            except ValueError:
                resolved_user_id = None
        legacy = and_(
            TenantMemberEntity.auth_user_uuid.is_(None),
            TenantMemberEntity.auth_user_id == subject.lower(),
        )
        return or_(TenantMemberEntity.auth_user_uuid == resolved_user_id, legacy) if resolved_user_id else legacy

    @staticmethod
    def _read(tenant: TenantEntity, role: str) -> TenantRead:
        return TenantRead(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            status=tenant.status,
            role=role,
            created_at=tenant.created_at,
            default_locale=tenant.default_locale,
            country_code=tenant.country_code,
            timezone=tenant.timezone,
            currency=tenant.currency,
            kind=tenant.kind,
            legal_name=tenant.legal_name,
            registration_country=tenant.registration_country,
            registration_type=tenant.registration_type,
            registration_masked=tenant.registration_masked,
            registration_verification_status=tenant.registration_verification_status,
        )

    @staticmethod
    def _audit(db, tenant_id: UUID, actor_id: str, action: str, metadata: dict[str, object]) -> None:
        db.add(AuditEventEntity(signature_request_id=None, occurred_at=DateTimeService.utc_now(), actor_type="user", actor_id=actor_id, action=action, entity_type="tenant", entity_id=tenant_id, correlation_id=uuid4(), metadata_sanitized=metadata))


tenant_service = TenantService()
