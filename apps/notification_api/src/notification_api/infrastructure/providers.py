from __future__ import annotations

from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import orjson
import redis

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.contracts.provider import (
    MessageProvider,
    ProviderDelivery,
)
from shared_kernel.media import LocalMediaStorage, MediaReference


class FakeMessageProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def deliver(
        self,
        *,
        recipient: str,
        content: str,
        media: MediaReference | None,
    ) -> ProviderDelivery:
        del recipient, content
        if media is not None:
            LocalMediaStorage(settings.MEDIA_STORAGE_ROOT).read_bytes(media)
        return ProviderDelivery(
            provider_message_id=f"fake-{uuid4()}",
            status="sent",
        )

    def verify(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "status": "ok",
            "mode": "fake",
            "credentials_required": False,
        }


_fake_providers = {
    "email": FakeMessageProvider("fake_email"),
    "slack": FakeMessageProvider("fake_slack"),
    "whatsapp": FakeMessageProvider("fake_whatsapp"),
}
_memory_deliveries: dict[str, dict[str, object]] = {}
_memory_lock = Lock()


def accept_delivery(
    *,
    channel: str,
    recipient: str,
    payload: dict,
    provider_name: str | None = None,
) -> dict[str, object]:
    policy = payload.get("delivery_policy") or {}
    policy_mode = policy.get("mode") or settings.NOTIFICATION_DELIVERY_DEFAULT_POLICY
    retention_seconds = (
        policy.get("retention_seconds")
        or settings.NOTIFICATION_DELIVERY_RETENTION_SECONDS
    )
    idempotency_key = str(payload.get("idempotency_key") or uuid4())
    cache_key = (
        f"{settings.NOTIFICATION_REDIS_KEY_PREFIX}:delivery:{channel}:{idempotency_key}"
    )
    existing = _load_delivery(cache_key)
    if existing is not None:
        return existing

    metadata = payload.get("metadata")
    tenant_id = metadata.get("tenant_id") if isinstance(metadata, dict) else None
    provider = _provider_for(
        channel,
        tenant_id=tenant_id,
        payload=payload,
        provider_name=provider_name,
    )
    media_payload = payload.get("media")
    media = (
        MediaReference.model_validate(media_payload)
        if isinstance(media_payload, dict)
        else None
    )
    delivery = provider.deliver(
        recipient=recipient,
        content=str(payload.get("body") or payload.get("content") or ""),
        media=media,
    )
    persisted = policy_mode != "transient" and settings.NOTIFICATION_REDIS_ENABLED
    payload_stored = False
    accepted: dict[str, object] = {
        "delivery_id": delivery.provider_message_id,
        "channel": channel,
        "recipient": recipient,
        "provider": provider.name,
        "status": delivery.status,
        "delivery_store": (
            "redis" if settings.NOTIFICATION_REDIS_ENABLED else "memory"
        ),
        "delivery_policy": policy_mode,
        "persisted": persisted,
        "payload_stored": payload_stored,
        "retention_seconds": retention_seconds if persisted else None,
        "payload": None,
    }
    return _store_delivery(cache_key, accepted, retention_seconds)


def _provider_for(
    channel: str,
    *,
    tenant_id: object = None,
    payload: dict[str, object] | None = None,
    provider_name: str | None = None,
) -> MessageProvider:
    selected_email_provider = provider_name or settings.NOTIFICATION_EMAIL_PROVIDER
    if channel == "email" and selected_email_provider == "resend":
        from notification_api.modules.messaging.domains.resend.resend_service import (
            ResendEmailProvider,
        )

        email_payload = payload or {}
        return ResendEmailProvider(
            subject=str(email_payload.get("subject") or "NexoDesk"),
            idempotency_key=str(email_payload.get("idempotency_key") or uuid4()),
        )
    if channel == "slack" and settings.SLACK_WEBHOOK_URL:
        from notification_api.modules.messaging.domains.slack.slack_service import (
            SlackWebhookProvider,
        )

        return SlackWebhookProvider()
    if channel == "whatsapp":
        if settings.NOTIFICATION_WHATSAPP_PROVIDER == "meta":
            from notification_api.modules.messaging.domains.meta.whatsapp.meta_service import (
                MetaWhatsappProvider,
            )

            return MetaWhatsappProvider(tenant_id=tenant_id)
        if settings.NOTIFICATION_WHATSAPP_PROVIDER == "twilio":
            from notification_api.modules.messaging.domains.twilio.whatsapp.twilio_service import (
                TwilioWhatsappProvider,
            )

            return TwilioWhatsappProvider()
    return _fake_providers.get(channel, FakeMessageProvider(f"fake_{channel}"))


def provider_catalog() -> dict[str, dict[str, object]]:
    selected_whatsapp = settings.NOTIFICATION_WHATSAPP_PROVIDER
    twilio_configured = bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN)
    meta_configured = bool(
        settings.META_WHATSAPP_ACCESS_TOKEN and settings.META_WHATSAPP_PHONE_NUMBER_ID
    )
    return {
        "fake": {
            "status": "available",
            "mode": "fake",
            "credentials_configured": True,
            "active": True,
            "channels": ["email", "slack", "whatsapp"],
            "whatsapp_selected": selected_whatsapp == "fake",
        },
        "sendgrid": {
            "status": "configured" if settings.SENDGRID_API_KEY else "not_configured",
            "mode": "external",
            "credentials_configured": bool(settings.SENDGRID_API_KEY),
            "selected": settings.NOTIFICATION_EMAIL_PROVIDER == "sendgrid",
            "active": False,
            "reason": "delivery_adapter_not_implemented",
        },
        "resend": {
            "status": "configured" if settings.RESEND_API_KEY else "not_configured",
            "mode": "external",
            "credentials_configured": bool(settings.RESEND_API_KEY),
            "selected": settings.NOTIFICATION_EMAIL_PROVIDER == "resend",
            "active": bool(
                settings.NOTIFICATION_EMAIL_PROVIDER == "resend"
                and settings.RESEND_API_KEY
            ),
            "channels": ["email"],
            "from": settings.RESEND_FROM_EMAIL,
        },
        "twilio": {
            "status": "configured" if twilio_configured else "not_configured",
            "mode": "external",
            "credentials_configured": twilio_configured,
            "selected": selected_whatsapp == "twilio",
            "active": selected_whatsapp == "twilio" and twilio_configured,
            "channels": ["whatsapp"],
        },
        "meta": {
            "status": "configured" if meta_configured else "not_configured",
            "mode": "external",
            "credentials_configured": meta_configured,
            "selected": selected_whatsapp == "meta",
            "active": selected_whatsapp == "meta" and meta_configured,
            "channels": ["whatsapp"],
            "webhook_configured": bool(
                settings.META_WHATSAPP_VERIFY_TOKEN
                and settings.META_APP_SECRET
            ),
            "graph_api_version": settings.META_GRAPH_API_VERSION,
        },
        "slack": {
            "status": "configured" if settings.SLACK_WEBHOOK_URL else "not_configured",
            "mode": "external",
            "credentials_configured": bool(settings.SLACK_WEBHOOK_URL),
            "active": bool(settings.SLACK_WEBHOOK_URL),
        },
    }


def verify_provider(provider_name: str) -> dict[str, object]:
    normalized = provider_name.strip().lower()
    if normalized == "fake":
        return FakeMessageProvider("fake").verify()
    if normalized == "sendgrid":
        if not settings.SENDGRID_API_KEY:
            return _not_configured("sendgrid")
        return _verify_http_credential(
            "sendgrid",
            Request(
                "https://api.sendgrid.com/v3/user/profile",
                headers={"Authorization": f"Bearer {settings.SENDGRID_API_KEY}"},
                method="GET",
            ),
        )
    if normalized == "resend":
        from notification_api.modules.messaging.domains.resend.resend_service import (
            verify_resend_credentials,
        )

        return verify_resend_credentials()
    if normalized == "twilio":
        from notification_api.modules.messaging.domains.twilio.whatsapp.twilio_service import (
            verify_twilio_credentials,
        )

        return verify_twilio_credentials()
    if normalized == "meta":
        from notification_api.modules.messaging.domains.meta.whatsapp.meta_service import (
            verify_meta_credentials,
        )

        return verify_meta_credentials()
    if normalized == "slack":
        if not settings.SLACK_WEBHOOK_URL:
            return _not_configured("slack")
        return {
            "provider": "slack",
            "status": "configured",
            "verified": False,
            "reason": "incoming_webhook_has_no_non_delivery_verification",
        }
    return {
        "provider": normalized,
        "status": "unsupported",
        "verified": False,
    }


def _verify_http_credential(
    provider_name: str,
    request: Request,
) -> dict[str, object]:
    try:
        with urlopen(request, timeout=5.0) as response:
            response.read(1)
        return {"provider": provider_name, "status": "ok", "verified": True}
    except HTTPError as exc:
        return {
            "provider": provider_name,
            "status": "invalid_credentials" if exc.code in {401, 403} else "unavailable",
            "verified": False,
            "http_status": exc.code,
        }
    except (OSError, URLError):
        return {
            "provider": provider_name,
            "status": "unavailable",
            "verified": False,
        }


def _not_configured(provider_name: str) -> dict[str, object]:
    return {
        "provider": provider_name,
        "status": "not_configured",
        "verified": False,
    }


def _load_delivery(key: str) -> dict[str, object] | None:
    if settings.NOTIFICATION_REDIS_ENABLED:
        client = redis.Redis.from_url(settings.NOTIFICATION_REDIS_URL)
        try:
            value = client.get(key)
            return orjson.loads(value) if value else None
        finally:
            client.close()
    with _memory_lock:
        value = _memory_deliveries.get(key)
        return dict(value) if value else None


def _store_delivery(
    key: str,
    value: dict[str, object],
    retention_seconds: int,
) -> dict[str, object]:
    if settings.NOTIFICATION_REDIS_ENABLED:
        client = redis.Redis.from_url(settings.NOTIFICATION_REDIS_URL)
        try:
            encoded = orjson.dumps(value)
            if client.set(key, encoded, ex=retention_seconds, nx=True):
                return value
            stored = client.get(key)
            return orjson.loads(stored) if stored else value
        finally:
            client.close()
    with _memory_lock:
        return dict(_memory_deliveries.setdefault(key, value))
