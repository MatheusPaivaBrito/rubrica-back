from fastapi import APIRouter, Depends, Header, Request, status
from uuid import UUID

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.modules.billing.billing_schema import (
    BillingAccountRead,
    BillingCheckoutRead,
    BillingPortalRead,
    BillingPaymentRead,
    BillingWebhookRead,
)
from core_api.modules.billing.billing_service import billing_service


router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/tenants/{tenant_id}/payments", response_model=list[BillingPaymentRead])
async def list_payments(
    tenant_id: UUID,
    context: AuthContext = Depends(require_permission("documents:read")),
) -> list[BillingPaymentRead]:
    return billing_service.payments(tenant_id, context.subject)


@router.get("/tenants/{tenant_id}/account", response_model=BillingAccountRead)
async def get_account(tenant_id: UUID, context: AuthContext = Depends(require_permission("documents:read"))) -> BillingAccountRead:
    return billing_service.account(tenant_id, context.subject)


@router.post("/tenants/{tenant_id}/account", response_model=BillingAccountRead, status_code=status.HTTP_201_CREATED)
async def initialize_account(tenant_id: UUID, context: AuthContext = Depends(require_permission("documents:write"))) -> BillingAccountRead:
    return billing_service.initialize(tenant_id, context.subject)


@router.post("/tenants/{tenant_id}/checkout", response_model=BillingCheckoutRead)
async def create_checkout(
    tenant_id: UUID,
    context: AuthContext = Depends(require_permission("documents:write")),
) -> BillingCheckoutRead:
    return billing_service.create_checkout(tenant_id, context.subject)


@router.post("/tenants/{tenant_id}/portal", response_model=BillingPortalRead)
async def create_portal(
    tenant_id: UUID,
    context: AuthContext = Depends(require_permission("documents:write")),
) -> BillingPortalRead:
    return billing_service.create_portal(tenant_id, context.subject)


@router.post("/webhooks/stripe", response_model=BillingWebhookRead)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="Stripe-Signature"),
) -> BillingWebhookRead:
    return billing_service.receive_webhook(await request.body(), stripe_signature)
