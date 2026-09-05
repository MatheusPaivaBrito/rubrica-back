from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from core_api.modules.billing.billing_errors import (
    BillingConfigurationError,
    BillingConflictError,
    BillingNotFoundError,
    BillingProviderError,
    BillingSignatureError,
)
from core_api.modules.billing.billing_schema import (
    BillingPaymentRead,
    BillingPlanRead,
    BillingSubscriptionRead,
    CheckoutCreate,
    CheckoutRead,
    MercadoPagoWebhookPayload,
    PublicCheckoutCreate,
    PublicCheckoutStatusRead,
    WebhookRead,
)
from core_api.modules.billing.billing_service import billing_service
from core_api.shared.auth import core_auth_guard
from core_api.shared.auth.context import RequestContext
from shared_kernel.identifiers import Identifier


router = APIRouter(
    prefix="/billing",
    tags=["billing"],
    dependencies=core_auth_guard.route_dependencies(),
)
webhook_router = APIRouter(prefix="/webhooks/billing", tags=["billing-webhooks"])
public_router = APIRouter(prefix="/public/billing", tags=["public-billing"])


def _manage_permission() -> None:
    core_auth_guard.require_permission("subscription.manage")


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, BillingNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, BillingSignatureError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, BillingConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, BillingProviderError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@public_router.get("/plans", response_model=list[BillingPlanRead])
def list_public_billing_plans() -> list[BillingPlanRead]:
    return billing_service.list_plans()


@public_router.post(
    "/checkouts", response_model=CheckoutRead, status_code=status.HTTP_201_CREATED
)
def create_public_billing_checkout(
    payload: PublicCheckoutCreate,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> CheckoutRead:
    try:
        return billing_service.create_public_checkout(payload, idempotency_key)
    except (
        BillingConflictError,
        BillingNotFoundError,
        BillingConfigurationError,
        BillingProviderError,
    ) as exc:
        raise _http_error(exc) from exc


@public_router.get("/checkouts/{checkout_id}", response_model=PublicCheckoutStatusRead)
def public_billing_checkout_status(checkout_id: Identifier) -> PublicCheckoutStatusRead:
    try:
        return billing_service.public_checkout_status(checkout_id)
    except (BillingConflictError, BillingNotFoundError) as exc:
        raise _http_error(exc) from exc


@router.get("/plans", response_model=list[BillingPlanRead])
def list_billing_plans() -> list[BillingPlanRead]:
    _manage_permission()
    return billing_service.list_plans()


@router.get("/subscription", response_model=BillingSubscriptionRead | None)
def current_billing_subscription(
    context: RequestContext = Depends(core_auth_guard.request_context),
) -> BillingSubscriptionRead | None:
    _manage_permission()
    try:
        return billing_service.current_subscription(context)
    except (BillingConflictError, BillingNotFoundError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/checkouts", response_model=CheckoutRead, status_code=status.HTTP_201_CREATED
)
def create_billing_checkout(
    payload: CheckoutCreate,
    context: RequestContext = Depends(core_auth_guard.request_context),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> CheckoutRead:
    _manage_permission()
    try:
        return billing_service.create_checkout(context, payload, idempotency_key)
    except (
        BillingConflictError,
        BillingNotFoundError,
        BillingConfigurationError,
        BillingProviderError,
    ) as exc:
        raise _http_error(exc) from exc


@router.get("/payments", response_model=list[BillingPaymentRead])
def list_billing_payments(
    context: RequestContext = Depends(core_auth_guard.request_context),
) -> list[BillingPaymentRead]:
    _manage_permission()
    return billing_service.list_payments(context)


@router.post("/subscription/cancel", response_model=BillingSubscriptionRead)
def cancel_billing_subscription(
    context: RequestContext = Depends(core_auth_guard.request_context),
) -> BillingSubscriptionRead:
    _manage_permission()
    try:
        return billing_service.cancel(context)
    except (
        BillingConflictError,
        BillingNotFoundError,
        BillingConfigurationError,
        BillingProviderError,
    ) as exc:
        raise _http_error(exc) from exc


@webhook_router.post("/mercado-pago", response_model=WebhookRead)
def mercado_pago_webhook(
    payload: MercadoPagoWebhookPayload,
    data_id: str | None = Query(default=None, alias="data.id"),
    x_signature: str | None = Header(default=None, alias="x-signature"),
    x_request_id: str | None = Header(default=None, alias="x-request-id"),
) -> WebhookRead:
    resource_id = data_id or str(payload.data.get("id") or "")
    if not resource_id:
        raise HTTPException(status_code=422, detail="Webhook resource ID is required")
    try:
        return billing_service.process_mercado_pago_webhook(
            payload=payload,
            data_id=resource_id,
            x_signature=x_signature,
            x_request_id=x_request_id,
        )
    except (
        BillingConflictError,
        BillingNotFoundError,
        BillingConfigurationError,
        BillingProviderError,
        BillingSignatureError,
    ) as exc:
        raise _http_error(exc) from exc
