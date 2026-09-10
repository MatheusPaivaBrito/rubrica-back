from base64 import b64encode
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import orjson

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.domains.twilio.whatsapp.twilio_schema import (
    TwilioMessageResponse,
)
from notification_api.modules.messaging.contracts.provider import ProviderDelivery
from shared_kernel.media import MediaReference


class TwilioWhatsappProvider:
    name = "twilio"

    def deliver(
        self,
        *,
        recipient: str,
        content: str,
        media: MediaReference | None,
    ) -> ProviderDelivery:
        if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
            raise RuntimeError("Twilio WhatsApp credentials are not configured")
        if media is not None:
            raise RuntimeError(
                "Twilio WhatsApp media delivery requires a provider-accessible media URL"
            )

        basic = _basic_authorization()
        payload = urlencode(
            {
                "From": _normalize_whatsapp_address(settings.TWILIO_WHATSAPP_FROM),
                "To": _normalize_whatsapp_address(recipient),
                "Body": content,
            }
        ).encode("utf-8")
        request = Request(
            "https://api.twilio.com/2010-04-01/Accounts/"
            f"{settings.TWILIO_ACCOUNT_SID}/Messages.json",
            data=payload,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=10.0) as response:
                parsed = TwilioMessageResponse.model_validate(
                    orjson.loads(response.read())
                )
        except HTTPError as exc:
            raise RuntimeError(
                f"Twilio WhatsApp delivery failed with HTTP {exc.code}"
            ) from exc
        except (OSError, URLError) as exc:
            raise RuntimeError("Twilio WhatsApp provider is unavailable") from exc

        return ProviderDelivery(
            provider_message_id=parsed.sid,
            status=parsed.status or "queued",
        )

    def verify(self) -> dict[str, object]:
        return verify_twilio_credentials()


def verify_twilio_credentials() -> dict[str, object]:
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        return {
            "provider": "twilio",
            "status": "not_configured",
            "verified": False,
        }

    request = Request(
        "https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.TWILIO_ACCOUNT_SID}.json",
        headers={"Authorization": f"Basic {_basic_authorization()}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=5.0) as response:
            response.read(1)
        return {"provider": "twilio", "status": "ok", "verified": True}
    except HTTPError as exc:
        return {
            "provider": "twilio",
            "status": (
                "invalid_credentials" if exc.code in {401, 403} else "unavailable"
            ),
            "verified": False,
            "http_status": exc.code,
        }
    except (OSError, URLError):
        return {
            "provider": "twilio",
            "status": "unavailable",
            "verified": False,
        }


def _basic_authorization() -> str:
    return b64encode(
        f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}".encode("utf-8")
    ).decode("ascii")


def _normalize_whatsapp_address(value: str) -> str:
    normalized = value.strip()
    if normalized.lower().startswith("whatsapp:"):
        return normalized
    return f"whatsapp:{normalized}"
