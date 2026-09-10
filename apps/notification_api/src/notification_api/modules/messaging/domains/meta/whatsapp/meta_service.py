from __future__ import annotations

from hmac import compare_digest, new as hmac_new
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import orjson
import redis

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.domains.meta.whatsapp.meta_schema import (
    MetaSendMessageResponse,
)
from notification_api.modules.messaging.domains.meta.whatsapp.meta_connection_repository import (
    get_meta_connection_repository,
)
from notification_api.modules.messaging.contracts.provider import ProviderDelivery
from shared_kernel.media import MediaReference
from shared_kernel.media import LocalMediaStorage
from shared_kernel.identifiers import Identifier


class MetaWhatsappProvider:
    name = "meta"

    def __init__(self, *, tenant_id: object = None) -> None:
        self._tenant_id = tenant_id

    def deliver(
        self,
        *,
        recipient: str,
        content: str,
        media: MediaReference | None,
    ) -> ProviderDelivery:
        if not settings.META_WHATSAPP_ACCESS_TOKEN:
            raise RuntimeError("Meta WhatsApp access token is not configured")
        phone_number_id = self._phone_number_id()
        if media is not None:
            raise RuntimeError(
                "Meta WhatsApp media delivery is not implemented for local MediaReference"
            )

        request = Request(
            _messages_url(phone_number_id),
            data=orjson.dumps(
                {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": _normalize_meta_recipient(recipient),
                    "type": "text",
                    "text": {"preview_url": False, "body": content},
                }
            ),
            headers={
                "Authorization": f"Bearer {settings.META_WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=10.0) as response:
                parsed = MetaSendMessageResponse.model_validate(
                    orjson.loads(response.read())
                )
        except HTTPError as exc:
            raise RuntimeError(_meta_delivery_error_message(exc)) from exc
        except (OSError, URLError) as exc:
            raise RuntimeError("Meta WhatsApp provider is unavailable") from exc

        if not parsed.messages:
            raise RuntimeError("Meta WhatsApp response did not include a message id")
        return ProviderDelivery(
            provider_message_id=parsed.messages[0].id,
            status="accepted",
        )

    def verify(self) -> dict[str, object]:
        return verify_meta_credentials()

    def _phone_number_id(self) -> str:
        if self._tenant_id is not None:
            try:
                tenant_id = Identifier(str(self._tenant_id))
            except (TypeError, ValueError):
                tenant_id = None
            if tenant_id is not None:
                connection = get_meta_connection_repository().get_by_tenant(tenant_id)
                if connection is not None and connection.status == "connected":
                    return connection.phone_number_id
        if settings.META_WHATSAPP_PHONE_NUMBER_ID:
            return settings.META_WHATSAPP_PHONE_NUMBER_ID
        raise RuntimeError("Meta WhatsApp phone number id is not configured")


def verify_meta_credentials() -> dict[str, object]:
    if not settings.META_WHATSAPP_ACCESS_TOKEN or not settings.META_WHATSAPP_PHONE_NUMBER_ID:
        return {
            "provider": "meta",
            "status": "not_configured",
            "verified": False,
        }

    request = Request(
        "https://graph.facebook.com/"
        f"{settings.META_GRAPH_API_VERSION}/{settings.META_WHATSAPP_PHONE_NUMBER_ID}",
        headers={"Authorization": f"Bearer {settings.META_WHATSAPP_ACCESS_TOKEN}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=5.0) as response:
            response.read(1)
        return {"provider": "meta", "status": "ok", "verified": True}
    except HTTPError as exc:
        return {
            "provider": "meta",
            "status": (
                "invalid_credentials" if exc.code in {400, 401, 403} else "unavailable"
            ),
            "verified": False,
            "http_status": exc.code,
        }
    except (OSError, URLError):
        return {
            "provider": "meta",
            "status": "unavailable",
            "verified": False,
        }


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not settings.META_APP_SECRET or not signature_header:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    expected = hmac_new(
        settings.META_APP_SECRET.encode("utf-8"),
        raw_body,
        "sha256",
    ).hexdigest()
    return compare_digest(signature_header[len(prefix) :], expected)


_memory_webhook_claims: set[str] = set()
_memory_webhook_lock = Lock()


def claim_meta_message(provider_message_id: str) -> bool:
    key = _webhook_key(provider_message_id)
    if settings.NOTIFICATION_REDIS_ENABLED:
        client = redis.Redis.from_url(settings.NOTIFICATION_REDIS_URL)
        try:
            return bool(
                client.set(
                    key,
                    b"1",
                    ex=settings.NOTIFICATION_DELIVERY_RETENTION_SECONDS,
                    nx=True,
                )
            )
        finally:
            client.close()
    with _memory_webhook_lock:
        if key in _memory_webhook_claims:
            return False
        _memory_webhook_claims.add(key)
        return True


def release_meta_message(provider_message_id: str) -> None:
    key = _webhook_key(provider_message_id)
    if settings.NOTIFICATION_REDIS_ENABLED:
        client = redis.Redis.from_url(settings.NOTIFICATION_REDIS_URL)
        try:
            client.delete(key)
        finally:
            client.close()
        return
    with _memory_webhook_lock:
        _memory_webhook_claims.discard(key)


def download_meta_media(
    media_id: str,
    *,
    tenant_id: Identifier,
) -> MediaReference:
    if not settings.META_WHATSAPP_ACCESS_TOKEN:
        raise RuntimeError("Meta WhatsApp access token is not configured")
    metadata_request = Request(
        "https://graph.facebook.com/"
        f"{settings.META_GRAPH_API_VERSION}/{media_id}",
        headers={"Authorization": f"Bearer {settings.META_WHATSAPP_ACCESS_TOKEN}"},
        method="GET",
    )
    try:
        with urlopen(metadata_request, timeout=10.0) as response:
            from notification_api.modules.messaging.domains.meta.whatsapp.meta_schema import (
                MetaMediaMetadata,
            )

            metadata = MetaMediaMetadata.model_validate(orjson.loads(response.read()))
        media_request = Request(
            metadata.url,
            headers={"Authorization": f"Bearer {settings.META_WHATSAPP_ACCESS_TOKEN}"},
            method="GET",
        )
        with urlopen(media_request, timeout=20.0) as response:
            data = response.read(25 * 1024 * 1024 + 1)
    except HTTPError as exc:
        raise RuntimeError(_meta_delivery_error_message(exc)) from exc
    except (OSError, URLError) as exc:
        raise RuntimeError("Meta WhatsApp media download is unavailable") from exc

    return LocalMediaStorage(settings.MEDIA_STORAGE_ROOT).store_bytes(
        data,
        tenant_id=tenant_id,
        scope="whatsapp-inbound",
        mime_type=metadata.mime_type,
        filename=f"whatsapp-{media_id}",
    )


def _meta_delivery_error_message(exc: HTTPError) -> str:
    details = [f"HTTP {exc.code}"]
    try:
        payload = orjson.loads(exc.read())
    except (orjson.JSONDecodeError, TypeError, ValueError):
        payload = None

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        for key in ("code", "error_subcode", "type", "message", "fbtrace_id"):
            value = error.get(key)
            if value is None or value == "":
                continue
            text = " ".join(str(value).split())
            details.append(f"{key}={text[:500]}")

    return "Meta WhatsApp delivery failed with " + ", ".join(details)


def _messages_url(phone_number_id: str) -> str:
    return (
        "https://graph.facebook.com/"
        f"{settings.META_GRAPH_API_VERSION}/{phone_number_id}/messages"
    )


def _normalize_meta_recipient(value: str) -> str:
    normalized = value.strip()
    if normalized.lower().startswith("whatsapp:"):
        normalized = normalized.split(":", 1)[1]
    return "".join(character for character in normalized if character.isdigit())


def _webhook_key(provider_message_id: str) -> str:
    return (
        f"{settings.NOTIFICATION_REDIS_KEY_PREFIX}:webhook:meta:"
        f"{provider_message_id}"
    )
