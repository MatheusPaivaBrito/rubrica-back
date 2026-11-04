from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from core_api.infrastructure.database.connection import Base
import core_api.infrastructure.database.loader  # noqa: F401
from core_api.modules.enterprise.machine_context import MachineContext
from core_api.modules.enterprise import telemetry, usage
from core_api.modules.enterprise.usage_entity import EnterpriseQuota, EnterpriseTelemetryOutbox, EnterpriseUsageEvent
from observability_api.modules.enterprise_usage import routes as projection
from observability_api.modules.enterprise_usage.entity import EnterpriseUsageRecord


@pytest.fixture
def usage_db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(telemetry, "SessionLocal", sessions)
    monkeypatch.setattr(usage.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(projection.settings, "ENVIRONMENT", "development")
    return sessions, MachineContext(uuid4(), uuid4(), uuid4(), "token-original", True)


def test_ledger_and_outbox_commit_together_without_rebilling(usage_db):
    sessions, context = usage_db
    signature_id = uuid4()
    with sessions.begin() as db:
        first = usage.record_usage(db, context, "signature.completed", signature_id)
        assert usage.record_usage(db, context, "signature.completed", signature_id).id == first.id
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(EnterpriseUsageEvent)) == 1
        assert db.scalar(select(func.count()).select_from(EnterpriseTelemetryOutbox)) == 1
        event = db.get(EnterpriseUsageEvent, first.id)
        assert event.amount_minor == 0
        assert event.billable is False
        assert usage.transport_fact(event).price_version == "enterprise-zero-v1"
    with pytest.raises(RuntimeError):
        with sessions.begin() as db:
            usage.record_usage(db, context, "document.uploaded", uuid4(), bytes_count=100)
            raise RuntimeError("rollback")
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(EnterpriseUsageEvent)) == 1


def test_sandbox_limits_are_shared_across_tokens_but_not_live(usage_db, monkeypatch):
    sessions, context = usage_db
    monkeypatch.setattr(usage.settings, "ENTERPRISE_SANDBOX_STORAGE_BYTES", 10)
    with sessions.begin() as db:
        usage.reserve_storage(db, context, 8, document=True)
    with pytest.raises(HTTPException) as error:
        with sessions.begin() as db:
            usage.reserve_storage(db, replace(context, token_public_id="new-token"), 3)
    assert error.value.status_code == 429
    with sessions.begin() as db:
        usage.reserve_storage(db, replace(context, sandbox=False), 100)
    with sessions() as db:
        rows = list(db.scalars(select(EnterpriseQuota)))
        assert sorted(item.storage_bytes for item in rows) == [8, 100]


def test_rate_budget_is_independent_from_storage_and_mode(usage_db, monkeypatch):
    sessions, context = usage_db
    now = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(usage.settings, "ENTERPRISE_SANDBOX_REQUESTS_PER_MINUTE", 1)
    with sessions.begin() as db:
        usage.reserve_api_request(db, context, now=now)
    with pytest.raises(HTTPException):
        with sessions.begin() as db:
            usage.reserve_api_request(db, replace(context, token_public_id="replacement"), now=now)
    with sessions.begin() as db:
        usage.reserve_api_request(db, replace(context, sandbox=False), now=now)


def test_projection_deduplicates_and_isolates_tenants(usage_db):
    sessions, context = usage_db
    with sessions.begin() as db:
        event = usage.record_usage(db, context, "signature.completed", uuid4())
        fact = usage.transport_fact(event)
    engine = create_engine("sqlite://")
    EnterpriseUsageRecord.__table__.create(engine)
    projection_sessions = sessionmaker(engine)
    with projection_sessions.begin() as db:
        projection.ingest(db, [fact, fact])
    with projection_sessions() as db:
        assert db.scalar(select(func.count()).select_from(EnterpriseUsageRecord)) == 1
        result = projection.summary(db, tenant_id=context.tenant_id, integration_id=context.integration_id, sandbox=True)
        assert result["totals"]["signatures"] == 1
        assert result["totals"]["billable_signatures"] == 0
        assert result["tokens"][0]["token_public_id"] == context.token_public_id
        wrong_tenant = projection.summary(db, tenant_id=uuid4(), integration_id=context.integration_id, sandbox=True)
        assert wrong_tenant["totals"]["signatures"] == 0
        wrong_mode = projection.summary(db, tenant_id=context.tenant_id, integration_id=context.integration_id, sandbox=False)
        assert wrong_mode["totals"]["signatures"] == 0
    with pytest.raises(HTTPException) as error:
        with projection_sessions.begin() as db:
            projection.ingest(db, [fact.model_copy(update={"units": 2})])
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        with projection_sessions.begin() as db:
            projection.ingest(db, [fact.model_copy(update={"environment": "staging"})])
    assert error.value.status_code == 403


def test_relay_failure_preserves_outbox_and_success_marks_delivered(usage_db, monkeypatch):
    sessions, context = usage_db
    monkeypatch.setattr(telemetry.settings, "OBSERVABILITY_INTERNAL_SERVICE_KEY", "internal-test-key")
    with sessions.begin() as db:
        event = usage.record_usage(db, context, "document.uploaded", uuid4(), bytes_count=100)
        event_id = event.id

    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(telemetry.httpx, "post", unavailable)
    assert telemetry.relay_once(sandbox=False) == 0
    assert telemetry.relay_once() == 0
    with sessions.begin() as db:
        job = db.scalar(select(EnterpriseTelemetryOutbox))
        assert job.delivered_at is None and job.attempts == 1
        job.next_attempt_at = datetime(2020, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(telemetry.httpx, "post", lambda *args, **kwargs:
        SimpleNamespace(status_code=200, json=lambda: {"accepted": [str(event_id)]}))
    assert telemetry.relay_once() == 1
    assert telemetry.relay_once() == 0


def test_sandbox_storage_has_separate_root_prefix_and_key():
    from core_api.modules.enterprise.storage_settings import for_mode
    original = usage.settings
    sandbox = for_mode(original, True)
    assert sandbox.DOCUMENT_STORAGE_PATH != original.DOCUMENT_STORAGE_PATH
    assert sandbox.R2_DOCUMENTS_PREFIX != original.R2_DOCUMENTS_PREFIX
    assert sandbox.DOCUMENT_STORAGE_ENCRYPTION_KEY != original.DOCUMENT_STORAGE_ENCRYPTION_KEY
    assert for_mode(original, False) is original
    assert for_mode(original, True, "legacy") is original
    with pytest.raises(ValueError):
        for_mode(original, True, "unknown")


def test_projection_rejects_calls_without_service_identity(monkeypatch):
    monkeypatch.setattr(projection.settings, "OBSERVABILITY_INTERNAL_SERVICE_KEY", "key")
    for service, key in (("", ""), ("core_api", "wrong"), ("other", "key")):
        with pytest.raises(HTTPException):
            projection.require_core(service, key)


def test_financial_fact_cannot_be_modified_in_place(usage_db):
    sessions, context = usage_db
    with sessions.begin() as db:
        event_id = usage.record_usage(db, context, "signature.completed", uuid4()).id
    with pytest.raises(ValueError, match="immutable"):
        with sessions.begin() as db:
            db.get(EnterpriseUsageEvent, event_id).amount_minor = 100
    with sessions() as db:
        assert db.get(EnterpriseUsageEvent, event_id).amount_minor == 0
