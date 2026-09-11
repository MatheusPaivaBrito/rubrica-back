from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from uuid import UUID

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.infrastructure.settings import settings
from core_api.modules.tenant.tenant_schema import (
    TenantCreate,
    TenantMemberCreate,
    TenantProvision,
    TenantPreferencesUpdate,
    TenantRead,
)
from core_api.modules.tenant.tenant_service import tenant_service
from shared_kernel.security.service_tokens import verify_service_token


router = APIRouter(prefix="/tenants", tags=["tenants"])
internal_router = APIRouter(prefix="/internal/tenants", tags=["internal tenants"])


@internal_router.post("/provision", response_model=TenantRead, include_in_schema=False)
async def provision_tenant(
    payload: TenantProvision,
    x_rubrica_service: str | None = Header(default=None),
    x_rubrica_service_key: str | None = Header(default=None),
) -> TenantRead:
    if (
        x_rubrica_service != "auth_api"
        or not settings.CORE_INTERNAL_SERVICE_KEY
        or not verify_service_token(
            x_rubrica_service_key or "",
            settings.CORE_INTERNAL_SERVICE_KEY,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service authentication failed",
        )
    return tenant_service.provision_owner(payload)


@router.get("", response_model=list[TenantRead])
async def list_tenants(context: AuthContext = Depends(require_permission("documents:read"))) -> list[TenantRead]:
    return tenant_service.list_for(context.subject)


@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
async def create_tenant(payload: TenantCreate, context: AuthContext = Depends(require_permission("documents:write"))) -> TenantRead:
    return tenant_service.create(payload, context.subject)


@router.post("/{tenant_id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def add_tenant_member(tenant_id: UUID, payload: TenantMemberCreate, context: AuthContext = Depends(require_permission("users:write"))) -> Response:
    tenant_service.add_member(tenant_id, payload, context.subject)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{tenant_id}/preferences", response_model=TenantRead)
async def update_tenant_preferences(
    tenant_id: UUID,
    payload: TenantPreferencesUpdate,
    context: AuthContext = Depends(require_permission("users:write")),
) -> TenantRead:
    return tenant_service.update_preferences(tenant_id, payload, context.subject)
