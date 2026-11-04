"""Persistent actor/tenant budgets after the existing authenticated MFA policy."""
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from core_api.infrastructure.auth_context import AuthContext, authenticated_context
from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.enterprise.execution_entity import EnterpriseAdministrationBudget
from core_api.modules.tenant.tenant_service import tenant_service


def reserve_budget(db, identity, limit, now):
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    digest = sha256(f"{settings.ENVIRONMENT}:{identity}".encode()).hexdigest()
    db.execute(insert(EnterpriseAdministrationBudget).values(id=uuid4(), identity=digest, minute=0, count=0)
        .on_conflict_do_nothing(index_elements=["identity"]))
    row = db.scalar(select(EnterpriseAdministrationBudget).where(EnterpriseAdministrationBudget.identity == digest).with_for_update())
    minute = int(now.timestamp()) // 60
    if row.minute != minute:
        row.minute, row.count = minute, 0
    if row.count >= limit:
        raise HTTPException(429, "Enterprise administration budget exceeded", headers={"Retry-After": "60"})
    row.count += 1


def administrative_guard(request: Request, context: AuthContext = Depends(authenticated_context)):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    tenant = UUID(request.path_params["tenant_id"])
    if not context.allows("documents:write"):
        raise HTTPException(403, "Permission denied")
    with SessionLocal.begin() as db:
        tenant_service.require_role(db, tenant, context.subject, {"admin"})
        now = datetime.now(UTC)
        reserve_budget(db, f"actor:{tenant}:{context.subject}", 30, now)
        reserve_budget(db, f"tenant:{tenant}", 120, now)
