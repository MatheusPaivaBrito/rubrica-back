import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
import logging
from time import perf_counter
from uuid import uuid4

import httpx
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.enterprise.usage import record_usage, transport_fact
from core_api.modules.enterprise.usage_entity import EnterpriseTelemetryOutbox, EnterpriseUsageEvent

logger = logging.getLogger(__name__)


def internal_headers():
    return {"X-Rubrica-Service": "core_api", "X-Rubrica-Service-Key": settings.OBSERVABILITY_INTERNAL_SERVICE_KEY}


def relay_once(*, sandbox=None):
    if not settings.OBSERVABILITY_INTERNAL_SERVICE_KEY:
        return 0
    now = datetime.now(UTC)
    with SessionLocal.begin() as db:
        statement = select(EnterpriseTelemetryOutbox).join(EnterpriseUsageEvent,
            EnterpriseUsageEvent.id == EnterpriseTelemetryOutbox.event_id).where(
            EnterpriseUsageEvent.environment == settings.ENVIRONMENT,
            EnterpriseTelemetryOutbox.delivered_at.is_(None),
            EnterpriseTelemetryOutbox.next_attempt_at <= now,
        )
        if sandbox is not None:
            statement = statement.where(EnterpriseUsageEvent.sandbox == sandbox)
        jobs = list(db.scalars(statement.order_by(EnterpriseTelemetryOutbox.next_attempt_at)
                               .limit(50).with_for_update(skip_locked=True)))
        if not jobs:
            return 0
        events = [transport_fact(db.get(EnterpriseUsageEvent, job.event_id)).model_dump(mode="json") for job in jobs]
        accepted = set()
        try:
            response = httpx.post(f"{settings.OBSERVABILITY_API_URL.rstrip('/')}/internal/observability/enterprise/events",
                headers=internal_headers(), json={"events": events}, timeout=3)
            if response.status_code == 200:
                accepted = set(response.json().get("accepted", []))
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            pass
        for job in jobs:
            job.attempts += 1
            if str(job.event_id) in accepted:
                job.delivered_at = now
            else:
                job.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(job.attempts, 8)))
        return sum(str(job.event_id) in accepted for job in jobs)


async def relay_loop():
    while True:
        full_batch = False
        try:
            for sandbox in (False, True):
                delivered = await asyncio.to_thread(relay_once, sandbox=sandbox)
                full_batch = full_batch or delivered == 50
        except Exception:
            logger.warning("Enterprise telemetry delivery deferred")
        await asyncio.sleep(0 if full_batch else 5)


async def storage_loop():
    from core_api.modules.enterprise.storage_migration import migrate_once
    from core_api.modules.enterprise.storage_removal import remove_once
    while True:
        for operation in (migrate_once, remove_once):
            try:
                await asyncio.to_thread(operation)
            except Exception:
                logger.warning("Enterprise storage operation deferred")
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_app):
    embedded = not settings.ENTERPRISE_DEDICATED_WORKERS
    task = asyncio.create_task(relay_loop()) if embedded and settings.ENTERPRISE_TELEMETRY_RELAY_ENABLED else None
    storage_task = asyncio.create_task(storage_loop()) if embedded and settings.ENTERPRISE_STORAGE_WORKER_ENABLED else None
    lifecycle_task = asyncio.create_task(lifecycle_loop()) if embedded and settings.ENTERPRISE_LIFECYCLE_WORKER_ENABLED else None
    processing = [asyncio.create_task(processing_loop(sandbox)) for sandbox in (False, True)] if embedded else []
    try:
        yield
    finally:
        for pending in (task, storage_task, lifecycle_task, *processing):
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending


async def processing_loop(sandbox):
    from core_api.modules.enterprise.worker import run_once
    while True:
        try:
            await asyncio.to_thread(run_once, sandbox=sandbox)
        except Exception:
            logger.warning("Enterprise processing deferred")
        await asyncio.sleep(1)


async def lifecycle_loop():
    from core_api.modules.enterprise.retention import synchronize_once, purge_once, email_notice_once
    from core_api.modules.enterprise.webhooks import dispatch_once
    from core_api.modules.enterprise.closure import finalize_once
    from core_api.modules.enterprise.worker import recover_once
    from core_api.modules.enterprise.housekeeping import cleanup_once
    while True:
        for operation in (synchronize_once, purge_once, email_notice_once, dispatch_once, recover_once, cleanup_once, finalize_once):
            try:
                await asyncio.to_thread(operation)
            except Exception:
                logger.warning("Enterprise lifecycle operation deferred")
        await asyncio.sleep(5)


def record_operational(context, kind, source_id, **kwargs):
    try:
        with SessionLocal.begin() as db:
            record_usage(db, context, kind, source_id, **kwargs)
    except Exception:
        # Operational samples must not invalidate successful business operations.
        logger.warning("Enterprise operational usage sample unavailable")


def apply_enterprise_telemetry(app):
    @app.middleware("http")
    async def observe(request, call_next):
        started, status_code = perf_counter(), 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            context = getattr(request.state, "machine_context", None)
            if context is not None:
                await asyncio.to_thread(record_operational, context, "api.request", uuid4(),
                    status_code=status_code, duration_ms=(perf_counter() - started) * 1000)
