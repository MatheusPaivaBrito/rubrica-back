from uuid import uuid4

from notification_api.infrastructure.settings import settings


def accept_delivery(*, channel: str, recipient: str, payload: dict) -> dict[str, object]:
    policy = payload.get("delivery_policy") or {}
    policy_mode = policy.get("mode") or settings.NOTIFICATION_DELIVERY_DEFAULT_POLICY
    retention_seconds = policy.get("retention_seconds") or settings.NOTIFICATION_DELIVERY_RETENTION_SECONDS
    persisted = policy_mode != "transient" and settings.NOTIFICATION_REDIS_ENABLED
    payload_stored = policy_mode == "reliable" and persisted
    return {
        "delivery_id": str(uuid4()),
        "channel": channel,
        "recipient": recipient,
        "provider": _provider_for(channel),
        "status": "accepted",
        "delivery_store": "redis" if settings.NOTIFICATION_REDIS_ENABLED else "memory",
        "delivery_policy": policy_mode,
        "persisted": persisted,
        "payload_stored": payload_stored,
        "retention_seconds": retention_seconds if persisted else None,
        "payload": payload if payload_stored else None,
    }


def _provider_for(channel: str) -> str:
    if channel == "email" and settings.SENDGRID_API_KEY:
        return "sendgrid"
    if channel == "slack" and settings.SLACK_WEBHOOK_URL:
        return "slack_webhook"
    if channel == "whatsapp" and settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        return "twilio"
    return "local_ack"
