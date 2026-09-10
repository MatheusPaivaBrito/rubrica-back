from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import orjson

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.contracts.provider import ProviderDelivery


class ResendEmailProvider:
    name = "resend"

    def __init__(self, *, subject: str, idempotency_key: str) -> None:
        self._subject = subject
        self._idempotency_key = idempotency_key

    def deliver(
        self,
        *,
        recipient: str,
        content: str,
        media: object | None,
    ) -> ProviderDelivery:
        if not settings.RESEND_API_KEY:
            raise RuntimeError("Resend API key is not configured")
        if media is not None:
            raise RuntimeError("Resend attachments are not supported in this flow")

        request = Request(
            "https://api.resend.com/emails",
            data=orjson.dumps(
                {
                    "from": settings.RESEND_FROM_EMAIL,
                    "to": [recipient],
                    "subject": self._subject,
                    "text": content,
                }
            ),
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
                "Idempotency-Key": self._idempotency_key,
                "User-Agent": "Rubrica/0.1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=10.0) as response:
                payload = orjson.loads(response.read())
        except HTTPError as exc:
            raise RuntimeError(_resend_error_message(exc)) from exc
        except (OSError, URLError, orjson.JSONDecodeError) as exc:
            raise RuntimeError("Resend provider is unavailable") from exc

        message_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(message_id, str) or not message_id:
            raise RuntimeError("Resend response did not include an e-mail id")
        return ProviderDelivery(provider_message_id=message_id, status="accepted")

    def verify(self) -> dict[str, object]:
        return verify_resend_credentials()


def verify_resend_credentials() -> dict[str, object]:
    if not settings.RESEND_API_KEY:
        return {
            "provider": "resend",
            "status": "not_configured",
            "verified": False,
        }
    request = Request(
        "https://api.resend.com/domains",
        headers={
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "User-Agent": "Rubrica/0.1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=5.0) as response:
            response.read(1)
        return {"provider": "resend", "status": "ok", "verified": True}
    except HTTPError as exc:
        return {
            "provider": "resend",
            "status": (
                "invalid_credentials" if exc.code == 401 else "restricted_or_unavailable"
            ),
            "verified": False,
            "http_status": exc.code,
        }
    except (OSError, URLError):
        return {
            "provider": "resend",
            "status": "unavailable",
            "verified": False,
        }


def _resend_error_message(exc: HTTPError) -> str:
    details = [f"HTTP {exc.code}"]
    raw_body = exc.read()
    try:
        payload = orjson.loads(raw_body)
    except (orjson.JSONDecodeError, TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        for key in ("name", "message"):
            value = payload.get(key)
            if value:
                details.append(f"{key}={' '.join(str(value).split())[:500]}")
    elif raw_body:
        details.append(f"message={' '.join(raw_body.decode(errors='replace').split())[:500]}")
    return "Resend delivery failed with " + ", ".join(details)
