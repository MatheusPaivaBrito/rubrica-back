from fastapi import APIRouter, Header, HTTPException, status

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.contracts.delivery import DeliveryAccepted
from notification_api.modules.messaging.domains.resend.resend_schema import ResendEmailRequest
from notification_api.modules.messaging.domains.resend.resend_service import ResendEmailProvider
from shared_kernel.security.service_tokens import verify_service_token


router = APIRouter(prefix="/internal/providers/resend", tags=["internal providers"])


@router.post("/emails", response_model=DeliveryAccepted, status_code=status.HTTP_202_ACCEPTED)
def send_resend_email(
    payload: ResendEmailRequest,
    x_rubrica_service: str | None = Header(default=None),
    x_rubrica_service_key: str | None = Header(default=None),
) -> DeliveryAccepted:
    if (
        x_rubrica_service not in settings.NOTIFICATION_INTERNAL_ALLOWED_SERVICES
        or not settings.NOTIFICATION_INTERNAL_SERVICE_KEY
        or not verify_service_token(
            x_rubrica_service_key or "",
            settings.NOTIFICATION_INTERNAL_SERVICE_KEY,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service authentication failed",
        )
    delivery = ResendEmailProvider(
        subject=payload.subject,
        idempotency_key=payload.idempotency_key,
    ).deliver(recipient=payload.recipient, content=payload.content, media=None)
    return DeliveryAccepted(
        delivery_id=delivery.provider_message_id,
        channel="email",
        recipient=payload.recipient,
        provider="resend",
        status=delivery.status,
        delivery_store="provider",
        delivery_policy="reliable",
        persisted=False,
        payload_stored=False,
        retention_seconds=None,
        payload=None,
    )
