from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from uuid import UUID

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_schema import (
    TenantCreate,
    TenantMemberCreate,
    TenantPreferencesUpdate,
    TenantRead,
)


class TenantService:
    def list_for(self, subject: str) -> list[TenantRead]:
        with SessionLocal() as db:
            rows = db.execute(
                select(TenantEntity, TenantMemberEntity.role)
                .join(TenantMemberEntity, TenantMemberEntity.tenant_id == TenantEntity.id)
                .where(TenantMemberEntity.auth_user_id == subject.lower(), TenantEntity.deleted_at.is_(None))
                .order_by(TenantEntity.name)
            ).all()
            return [self._read(tenant, role) for tenant, role in rows]

    def create(self, payload: TenantCreate, subject: str) -> TenantRead:
        with SessionLocal.begin() as db:
            tenant = TenantEntity(
                name=payload.name.strip(),
                slug=payload.slug,
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
            db.add(TenantMemberEntity(tenant_id=tenant.id, auth_user_id=subject.lower(), role="admin"))
            db.flush()
            return self._read(tenant, "admin")

    def add_member(self, tenant_id: UUID, payload: TenantMemberCreate, subject: str) -> None:
        with SessionLocal.begin() as db:
            self.require_role(db, tenant_id, subject, {"admin"})
            db.add(TenantMemberEntity(tenant_id=tenant_id, auth_user_id=payload.auth_user_id.lower(), role=payload.role))
            try:
                db.flush()
            except IntegrityError as exc:
                raise WorkflowError("User is already a tenant member", 409) from exc

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
        member = db.scalar(select(TenantMemberEntity).where(TenantMemberEntity.tenant_id == tenant_id, TenantMemberEntity.auth_user_id == subject.lower(), TenantMemberEntity.deleted_at.is_(None)))
        if member is None or (roles is not None and member.role not in roles):
            raise WorkflowError("Tenant access denied", 403)
        return member

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
        )


tenant_service = TenantService()
