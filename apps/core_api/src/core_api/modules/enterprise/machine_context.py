"""Machine authentication delegates credential verification exclusively to Auth."""

from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseIntegration
from sqlalchemy import select


class AuthClaims(BaseModel):
    tenant_id: UUID
    integration_id: UUID
    public_id: str
    environment: str
    sandbox: bool
    scopes: frozenset[str]


@dataclass(frozen=True)
class MachineContext:
    tenant_id: UUID
    integration_id: UUID
    compartment_id: UUID
    token_public_id: str
    sandbox: bool


def authorize_binding(db, claims: AuthClaims, compartment_id: UUID) -> MachineContext:
    item = db.scalar(select(EnterpriseIntegration).where(
        EnterpriseIntegration.id == claims.integration_id,
        EnterpriseIntegration.tenant_id == claims.tenant_id,
        EnterpriseIntegration.environment == settings.ENVIRONMENT,
        EnterpriseIntegration.sandbox == claims.sandbox,
        EnterpriseIntegration.enabled.is_(True),
        EnterpriseIntegration.deleted_at.is_(None),
    ))
    if item is None:
        raise HTTPException(403, "Integration unavailable")
    account = db.scalar(select(BillingAccountEntity).where(
        BillingAccountEntity.tenant_id == claims.tenant_id,
        BillingAccountEntity.current_product_code == "rubrica_enterprise",
        BillingAccountEntity.deleted_at.is_(None),
    ))
    if account is None:
        raise HTTPException(403, "Active enterprise contract required")
    from core_api.modules.enterprise.lifecycle import require_operational
    require_operational(db, account)
    compartment = db.scalar(select(EnterpriseCompartment).where(
        EnterpriseCompartment.id == compartment_id,
        EnterpriseCompartment.integration_id == claims.integration_id,
        EnterpriseCompartment.deleted_at.is_(None),
    ))
    if compartment is None:
        raise HTTPException(404, "Compartment not found")
    return MachineContext(claims.tenant_id, claims.integration_id, compartment_id,
                          claims.public_id, claims.sandbox)


def require_machine(permission: str):
    async def dependency(request: Request, compartment_id: UUID) -> MachineContext:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or not 1 <= len(authorization) <= 263:
            raise HTTPException(401, "Machine credential required")
        sandbox = request.url.path.startswith("/api/v1/sandbox/")
        if not settings.CORE_INTERNAL_SERVICE_KEY:
            raise HTTPException(503, "Machine authentication unavailable")
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    f"{settings.AUTH_API_URL.rstrip('/')}/internal/machine-credentials/introspect",
                    headers={"X-Rubrica-Service": "core_api",
                             "X-Rubrica-Service-Key": settings.CORE_INTERNAL_SERVICE_KEY},
                    json={"secret": authorization[7:], "sandbox": sandbox, "permission": permission},
                )
            if response.status_code == 401:
                raise HTTPException(401, "Invalid machine credential")
            if response.status_code != 200:
                raise HTTPException(503, "Machine authentication unavailable")
            claims = AuthClaims.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise HTTPException(503, "Machine authentication unavailable") from exc
        if claims.environment != settings.ENVIRONMENT or claims.sandbox != sandbox or permission not in claims.scopes:
            raise HTTPException(403, "Machine scope mismatch")
        with SessionLocal() as db:
            context = authorize_binding(db, claims, compartment_id)
        request.state.machine_context = context
        from core_api.modules.enterprise.usage import reserve_api_request
        with SessionLocal.begin() as db:
            reserve_api_request(db, context)
        return context
    return dependency
