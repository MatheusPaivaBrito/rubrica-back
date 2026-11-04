from datetime import datetime
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseIntegration
from core_api.modules.tenant.tenant_service import tenant_service

router = APIRouter(prefix="/enterprise/tenants/{tenant_id}", tags=["enterprise administration"])


class IntegrationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160, pattern=r"\S")
    sandbox: bool = True


class IntegrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    sandbox: bool
    environment: str
    enabled: bool


class CompartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160, pattern=r"\S")


class CompartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    integration_id: UUID
    name: str


class TokenRotation(BaseModel):
    scopes: frozenset[str]
    expires_at: datetime | None = None


class IntegrationState(BaseModel):
    enabled: bool


@router.patch("/integrations/{integration_id}", response_model=IntegrationRead)
def change_integration(tenant_id: UUID, integration_id: UUID, payload: IntegrationState,
                       context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal.begin() as db:
        item = binding(db, tenant_id, integration_id, context, recovery=True)
        if payload.enabled:
            require_enterprise(db, tenant_id, context)
        item.enabled = payload.enabled
        tenant_service._audit(db, tenant_id, context.subject, "enterprise.integration.state_changed", {
            "integration_id": str(item.id), "enabled": item.enabled})
        return IntegrationRead.model_validate(item)


def require_enterprise(db, tenant_id, context, *, recovery=False):
    tenant_service.require_role(db, tenant_id, context.subject, {"admin"})
    account = db.scalar(select(BillingAccountEntity).where(
        BillingAccountEntity.tenant_id == tenant_id,
        BillingAccountEntity.deleted_at.is_(None),
    ).with_for_update())
    if account is None:
        raise HTTPException(403, "Active enterprise contract required")
    from core_api.modules.enterprise.lifecycle import contract_view, lifecycle_for
    state = lifecycle_for(db, tenant_id)
    if account.current_product_code != "rubrica_enterprise" and not (recovery and state):
        raise HTTPException(403, "Active enterprise contract required")
    view = contract_view(account, state)
    if not view["operational"] and not (recovery and view["recovery"]):
        raise HTTPException(403, "Enterprise contract suspended")


def binding(db, tenant_id, integration_id, context, *, recovery=False):
    require_enterprise(db, tenant_id, context, recovery=recovery)
    item = db.scalar(select(EnterpriseIntegration).where(
        EnterpriseIntegration.id == integration_id,
        EnterpriseIntegration.tenant_id == tenant_id,
        EnterpriseIntegration.deleted_at.is_(None),
        EnterpriseIntegration.environment == settings.ENVIRONMENT,
    ).with_for_update())
    if item is None:
        raise HTTPException(404, "Integration not found")
    if not item.enabled and not recovery:
        raise HTTPException(409, "Integration is disabled")
    return item


def require_storage_access(db, tenant_id, context):
    return require_enterprise(db, tenant_id, context, recovery=True)


def recovery_binding(db, tenant_id, integration_id, context):
    return binding(db, tenant_id, integration_id, context, recovery=True)


@router.post("/integrations", response_model=IntegrationRead, status_code=201)
def create_integration(tenant_id: UUID, payload: IntegrationCreate,
                       context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal.begin() as db:
        require_enterprise(db, tenant_id, context)
        item = EnterpriseIntegration(tenant_id=tenant_id, name=payload.name.strip(),
            environment=settings.ENVIRONMENT, sandbox=payload.sandbox, created_by=context.subject)
        db.add(item)
        db.flush()
        tenant_service._audit(db, tenant_id, context.subject, "enterprise.integration.created", {"integration_id": str(item.id)})
        return IntegrationRead.model_validate(item)


@router.get("/integrations", response_model=list[IntegrationRead])
def list_integrations(tenant_id: UUID,
                      context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        require_storage_access(db, tenant_id, context)
        return [IntegrationRead.model_validate(item) for item in db.scalars(
            select(EnterpriseIntegration).where(EnterpriseIntegration.tenant_id == tenant_id,
                EnterpriseIntegration.deleted_at.is_(None),
                EnterpriseIntegration.environment == settings.ENVIRONMENT).limit(100))]


@router.post("/integrations/{integration_id}/compartments", response_model=CompartmentRead, status_code=201)
def create_compartment(tenant_id: UUID, integration_id: UUID, payload: CompartmentCreate,
                       context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal.begin() as db:
        binding(db, tenant_id, integration_id, context)
        item = EnterpriseCompartment(integration_id=integration_id, name=payload.name.strip())
        db.add(item)
        db.flush()
        tenant_service._audit(db, tenant_id, context.subject, "enterprise.compartment.created", {"compartment_id": str(item.id), "integration_id": str(integration_id)})
        return CompartmentRead.model_validate(item)


@router.get("/integrations/{integration_id}/compartments", response_model=list[CompartmentRead])
def list_compartments(tenant_id: UUID, integration_id: UUID,
                      context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        binding(db, tenant_id, integration_id, context)
        return [CompartmentRead.model_validate(item) for item in db.scalars(
            select(EnterpriseCompartment).where(EnterpriseCompartment.integration_id == integration_id,
                EnterpriseCompartment.deleted_at.is_(None)).limit(100))]


def credential_operation(tenant_id, integration_id, context, operation, extra):
    if not settings.CORE_INTERNAL_SERVICE_KEY:
        raise HTTPException(503, "Credential administration unavailable")
    with SessionLocal.begin() as db:
        item = binding(db, tenant_id, integration_id, context)
        try:
            result = httpx.post(
                f"{settings.AUTH_API_URL.rstrip('/')}/internal/machine-credentials/{operation}",
                headers={"X-Rubrica-Service": "core_api", "X-Rubrica-Service-Key": settings.CORE_INTERNAL_SERVICE_KEY},
                json={"tenant_id": str(tenant_id), "integration_id": str(integration_id),
                      "subject": context.subject, "environment": item.environment,
                      "sandbox": item.sandbox, **extra}, timeout=5,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(503, "Credential administration unavailable") from exc
        if result.status_code not in {200, 204}:
            raise HTTPException(502, "Credential operation rejected")
        return result.json() if result.status_code == 200 else None


@router.post("/integrations/{integration_id}/token")
def rotate(tenant_id: UUID, integration_id: UUID, payload: TokenRotation, response: Response,
           context: AuthContext = Depends(require_permission("documents:write"))):
    response.headers["Cache-Control"] = "no-store"
    return credential_operation(tenant_id, integration_id, context, "rotate", payload.model_dump(mode="json"))


@router.delete("/integrations/{integration_id}/token", status_code=204)
def revoke(tenant_id: UUID, integration_id: UUID,
           context: AuthContext = Depends(require_permission("documents:write"))):
    credential_operation(tenant_id, integration_id, context, "revoke", {})
