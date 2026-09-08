from fastapi import APIRouter, Depends, Response, status
from uuid import UUID

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.modules.tenant.tenant_schema import TenantCreate, TenantMemberCreate, TenantRead
from core_api.modules.tenant.tenant_service import tenant_service


router = APIRouter(prefix="/tenants", tags=["tenants"])


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
