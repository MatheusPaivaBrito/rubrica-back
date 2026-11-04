"""Durable at-least-once webhooks: bounded TLS transport and HMAC replay window."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import hmac
import json
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
import httpx
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.enterprise.entities import EnterpriseIntegration
from core_api.modules.enterprise.lifecycle_entity import EnterpriseWebhook, EnterpriseWebhookDelivery
from core_api.modules.enterprise.provider_vault import decrypt_configuration
from core_api.modules.enterprise.s3_destination import pinned_address


def webhook_url(url):
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(422, "Invalid webhook URL") from exc
    allowed = {host.strip().lower() for host in settings.ENTERPRISE_WEBHOOK_ALLOWED_HOSTS.split(",") if host.strip()}
    if (parsed.scheme != "https" or not parsed.hostname or port not in {443, None} or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.hostname.lower() not in allowed):
        raise HTTPException(422, "Webhook requires an operator-approved HTTPS hostname, without credentials or query")
    return parsed


def enqueue(db, integration, event_id, kind, data, *, now=None):
    endpoint = db.scalar(select(EnterpriseWebhook).where(EnterpriseWebhook.integration_id == integration.id,
        EnterpriseWebhook.enabled.is_(True)))
    if endpoint is None:
        return
    if db.scalar(select(EnterpriseWebhookDelivery.id).where(EnterpriseWebhookDelivery.endpoint_id == endpoint.id,
        EnterpriseWebhookDelivery.event_id == event_id)):
        return
    now = now or datetime.now(UTC)
    payload = {"id": str(event_id), "type": kind, "created_at": now.isoformat(), "tenant_id": str(integration.tenant_id),
               "integration_id": str(integration.id), "sandbox": integration.sandbox,
               "environment": integration.environment, "data": data}
    db.add(EnterpriseWebhookDelivery(endpoint_id=endpoint.id, event_id=event_id, payload=payload,
        next_attempt_at=now, retry_until=now + timedelta(hours=24)))
    db.flush()


def enqueue_notice(db, item):
    for integration in db.scalars(select(EnterpriseIntegration).where(EnterpriseIntegration.tenant_id == item.tenant_id,
        EnterpriseIntegration.environment == settings.ENVIRONMENT, EnterpriseIntegration.deleted_at.is_(None))):
        enqueue(db, integration, uuid5(NAMESPACE_URL, f"rubrica.notice:{item.id}:{integration.id}"), item.kind, item.payload)


def canonical_body(payload):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(body) > 16_384:
        raise ValueError("Webhook event exceeds delivery budget")
    return body


def signed_headers(secret, body, timestamp, event_id, version):
    signature = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Rubrica-Event-Id": str(event_id),
            "X-Rubrica-Signature": f"t={timestamp},v1={signature}", "X-Rubrica-Key-Version": str(version)}


def deliver(endpoint, integration, job, now):
    parsed = webhook_url(endpoint.url)
    ip = pinned_address(parsed.hostname)
    host = f"[{ip}]" if ":" in ip else ip
    url = f"https://{host}{parsed.path or '/'}"
    config = decrypt_configuration(integration.tenant_id, f"webhook:{endpoint.id}", integration.sandbox,
                                   endpoint.secret_version, endpoint.encrypted_secret)
    body = canonical_body(job.payload)
    headers = signed_headers(config["secret"], body, int(now.timestamp()), job.event_id, endpoint.secret_version)
    headers["Host"] = parsed.hostname
    with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
        with client.stream("POST", url, headers=headers, content=body, extensions={"sni_hostname": parsed.hostname}) as response:
            return response.status_code  # Do not consume an unbounded customer response body.


def dispatch_once(*, now=None):
    now = now or datetime.now(UTC)
    with SessionLocal.begin() as db:
        job = db.scalar(select(EnterpriseWebhookDelivery).join(EnterpriseWebhook,
            EnterpriseWebhook.id == EnterpriseWebhookDelivery.endpoint_id).join(EnterpriseIntegration,
            EnterpriseIntegration.id == EnterpriseWebhook.integration_id).where(
            EnterpriseIntegration.environment == settings.ENVIRONMENT, EnterpriseWebhookDelivery.status == "pending",
            EnterpriseWebhookDelivery.next_attempt_at <= now).order_by(EnterpriseWebhookDelivery.next_attempt_at)
            .limit(1).with_for_update(of=EnterpriseWebhookDelivery, skip_locked=True))
        if job is None:
            return False
        endpoint = db.get(EnterpriseWebhook, job.endpoint_id)
        integration = db.get(EnterpriseIntegration, endpoint.integration_id)
        if (job.payload.get("environment") != settings.ENVIRONMENT
                or job.payload.get("tenant_id") != str(integration.tenant_id)
                or job.payload.get("integration_id") != str(integration.id)
                or job.payload.get("sandbox") is not integration.sandbox):
            job.status, job.error_code = "dead", "event_binding_mismatch"
            return True
        expiry = job.retry_until.replace(tzinfo=UTC) if job.retry_until.tzinfo is None else job.retry_until
        if not endpoint.enabled or now >= expiry:
            job.status, job.error_code = "dead", "disabled_or_retry_window_expired"
            return True
        job.attempts += 1
        try:
            status = deliver(endpoint, integration, job, now)
        except Exception:
            status = 0
        if 200 <= status < 300:
            job.status, job.error_code = "delivered", None
        elif status in {400, 401, 403, 404, 410, 422}:
            job.status, job.error_code = "dead", "destination_rejected"
        else:
            job.next_attempt_at = now + timedelta(seconds=min(3600, 2 ** min(job.attempts + 2, 12)))
            job.error_code = "delivery_unconfirmed"
        return True
