from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.billing.billing_schema import BillingAccountRead
from core_api.modules.tenant.tenant_service import tenant_service


class BillingService:
    def account(self, tenant_id: int, subject: str) -> BillingAccountRead:
        return self._account(tenant_id, subject, {"admin", "auditor"})

    def initialize(self, tenant_id: int, subject: str) -> BillingAccountRead:
        return self._account(tenant_id, subject, {"admin"})

    @staticmethod
    def _account(tenant_id: int, subject: str, roles: set[str]) -> BillingAccountRead:
        with SessionLocal.begin() as db:
            tenant_service.require_role(db, tenant_id, subject, roles)
            account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id, BillingAccountEntity.deleted_at.is_(None)))
            if account is None:
                account = BillingAccountEntity(tenant_id=tenant_id, status="not_configured")
                db.add(account)
                db.flush()
            return BillingAccountRead.model_validate(account)


billing_service = BillingService()
