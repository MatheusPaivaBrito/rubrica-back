from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from core_api.infrastructure.settings import settings
from core_api.modules.enterprise.usage_entity import EnterpriseApiRateBucket, EnterpriseQuota, EnterpriseTelemetryOutbox, EnterpriseUsageEvent
from shared_kernel.enterprise_usage import EnterpriseUsageFact


def quota_row(db, context):
    db.flush()
    table = EnterpriseQuota.__table__
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.execute(insert(table).values(id=uuid4(), tenant_id=context.tenant_id,
        sandbox=context.sandbox, storage_bytes=0, document_count=0,
        signing_day=0, signing_count=0).on_conflict_do_nothing(
            index_elements=["tenant_id", "sandbox"]))
    return db.scalar(select(EnterpriseQuota).where(EnterpriseQuota.tenant_id == context.tenant_id,
        EnterpriseQuota.sandbox == context.sandbox).with_for_update().execution_options(populate_existing=True))


def reserve_api_request(db, context, *, now=None):
    now = now or datetime.now(UTC)
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.execute(insert(EnterpriseApiRateBucket).values(id=uuid4(), tenant_id=context.tenant_id,
        sandbox=context.sandbox, minute=0, count=0).on_conflict_do_nothing(index_elements=["tenant_id", "sandbox"]))
    row = db.scalar(select(EnterpriseApiRateBucket).where(
        EnterpriseApiRateBucket.tenant_id == context.tenant_id,
        EnterpriseApiRateBucket.sandbox == context.sandbox,
    ).with_for_update())
    minute = int(now.timestamp()) // 60
    if row.minute != minute:
        row.minute, row.count = minute, 0
    limit = settings.ENTERPRISE_SANDBOX_REQUESTS_PER_MINUTE if context.sandbox else settings.ENTERPRISE_REQUESTS_PER_MINUTE
    if row.count >= limit:
        raise HTTPException(429, "Tenant API rate limit reached", headers={"Retry-After": str(60 - int(now.timestamp()) % 60)})
    row.count += 1


def reserve_storage(db, context, size, *, document=False):
    row = quota_row(db, context)
    if context.sandbox and (row.storage_bytes + size > settings.ENTERPRISE_SANDBOX_STORAGE_BYTES
            or (document and row.document_count >= settings.ENTERPRISE_SANDBOX_DOCUMENT_LIMIT)):
        raise HTTPException(429, "Sandbox storage allowance exhausted")
    row.storage_bytes += size
    if document:
        row.document_count += 1


def reserve_signature(db, context, *, now=None):
    now = now or datetime.now(UTC)
    row = quota_row(db, context)
    day = int(now.timestamp()) // 86400
    if row.signing_day != day:
        row.signing_day, row.signing_count = day, 0
    limit = settings.ENTERPRISE_SANDBOX_SIGNATURES_PER_DAY if context.sandbox else settings.ENTERPRISE_SIGNATURES_PER_DAY
    if row.signing_count >= limit:
        raise HTTPException(429, "Daily signing capacity exhausted")
    row.signing_count += 1


def record_usage(db, context, kind, source_id, *, bytes_count=0, now=None, status_code=None, duration_ms=None):
    fact = EnterpriseUsageFact(id=uuid5(NAMESPACE_URL, f"rubrica.enterprise.{kind}:{source_id}"),
        source_id=source_id, tenant_id=context.tenant_id, integration_id=context.integration_id,
        compartment_id=context.compartment_id, token_public_id=context.token_public_id,
        environment=settings.ENVIRONMENT, sandbox=context.sandbox, kind=kind, bytes_count=bytes_count,
        billable=kind == "signature.completed" and not context.sandbox,
        occurred_at=now or datetime.now(UTC), status_code=status_code, duration_ms=duration_ms)
    existing = db.get(EnterpriseUsageEvent, fact.id)
    if existing is not None:
        if (existing.tenant_id != context.tenant_id or existing.integration_id != context.integration_id
                or existing.compartment_id != context.compartment_id or existing.sandbox != context.sandbox
                or existing.environment != settings.ENVIRONMENT or existing.bytes_count != bytes_count):
            raise ValueError("Usage source conflicts with an existing immutable fact")
        return existing
    values = fact.model_dump(exclude={"schema_version"})
    event = EnterpriseUsageEvent(**values)
    db.add(event)
    db.flush()
    db.add(EnterpriseTelemetryOutbox(event_id=event.id, next_attempt_at=fact.occurred_at))
    db.flush()
    if kind in {"document.uploaded", "signature.completed", "storage.exported", "storage.removed", "storage.added"}:
        from core_api.modules.enterprise.entities import EnterpriseIntegration
        from core_api.modules.enterprise.webhooks import enqueue
        integration = db.get(EnterpriseIntegration, context.integration_id)
        if integration is not None:
            enqueue(db, integration, event.id, kind, {"source_id": str(source_id),
                "compartment_id": str(context.compartment_id), "bytes_count": bytes_count})
    return event


def transport_fact(event):
    occurred_at = event.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return EnterpriseUsageFact(**{name: getattr(event, name) for name in (
        "id", "source_id", "tenant_id", "integration_id", "compartment_id", "token_public_id",
        "environment", "sandbox", "kind", "units", "bytes_count", "billable", "amount_minor",
        "currency", "price_version", "status_code", "duration_ms")}, occurred_at=occurred_at)
