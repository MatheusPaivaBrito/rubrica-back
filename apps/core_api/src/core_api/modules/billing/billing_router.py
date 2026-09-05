from fastapi import APIRouter, Depends, status

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.modules.billing.billing_schema import BillingAccountRead
from core_api.modules.billing.billing_service import billing_service


router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/tenants/{tenant_id}/account", response_model=BillingAccountRead)
async def get_account(tenant_id: int, context: AuthContext = Depends(require_permission("documents:read"))) -> BillingAccountRead:
    return billing_service.account(tenant_id, context.subject)


@router.post("/tenants/{tenant_id}/account", response_model=BillingAccountRead, status_code=status.HTTP_201_CREATED)
async def initialize_account(tenant_id: int, context: AuthContext = Depends(require_permission("documents:write"))) -> BillingAccountRead:
    return billing_service.initialize(tenant_id, context.subject)
