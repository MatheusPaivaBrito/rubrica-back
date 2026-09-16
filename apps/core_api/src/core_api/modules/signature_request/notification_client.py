import httpx

from core_api.infrastructure.settings import settings


class SignatureInvitationDeliveryError(RuntimeError):
    pass


def send_signature_invitation(
    *, recipient: str, signer_name: str, document_title: str, signing_url: str, idempotency_key: str
) -> None:
    try:
        response = httpx.post(
            f"{settings.NOTIFICATION_API_URL.rstrip('/')}/internal/providers/resend/emails",
            json={
                "recipient": recipient,
                "subject": f"Rubrica: assinatura solicitada para {document_title}",
                "content": (
                    f"Olá, {signer_name}. Você recebeu uma solicitação para assinar "
                    f"o documento '{document_title}'. Acesse com sua conta Rubrica: "
                    f"{signing_url}\n\n"
                    f"Hello, {signer_name}. You were invited to sign '{document_title}'. "
                    f"Sign in with your Rubrica account: {signing_url}"
                ),
                "idempotency_key": idempotency_key,
            },
            headers={
                "X-Rubrica-Service": "core_api",
                "X-Rubrica-Service-Key": settings.NOTIFICATION_INTERNAL_SERVICE_KEY,
            },
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SignatureInvitationDeliveryError(
            "Signature invitation delivery is unavailable"
        ) from exc
