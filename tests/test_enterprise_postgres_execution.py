"""Real PostgreSQL lock/crash contracts. Use a dedicated disposable test database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import importlib
import os
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

import test_enterprise_workflow as workflows
from core_api.modules.enterprise import jobs, provider_operations, signing_service
from core_api.modules.enterprise.execution_entity import EnterpriseOperation
from core_api.modules.enterprise.entities import EnterpriseSignature
from core_api.modules.signature_request import serpro_timestamp_service


@pytest.fixture
def pg_workflow(monkeypatch, tmp_path):
    dsn = os.getenv("RUBRICA_ENTERPRISE_TEST_POSTGRES_DSN", "")
    if not dsn:
        pytest.skip("Dedicated PostgreSQL integration DSN not configured")
    url = make_url(dsn)
    if url.database != "rubrica_enterprise_test" or url.host not in {"127.0.0.1", "localhost"}:
        pytest.fail("Only the explicit disposable loopback test database is accepted")
    root = create_engine(dsn)
    schema = "part14_" + uuid4().hex
    with root.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(dsn, connect_args={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr(workflows, "create_engine", lambda _: engine)
    env = workflows.workflow.__wrapped__(monkeypatch, tmp_path)
    monkeypatch.setattr(jobs, "SessionLocal", env[2])
    try:
        yield env
    finally:
        engine.dispose()
        with root.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


def test_postgres_concurrent_admission_respects_tenant_limit(pg_workflow, monkeypatch):
    context, document, sessions, _ = pg_workflow
    monkeypatch.setattr(jobs.settings, "ENTERPRISE_QUEUE_LIMIT", 5)
    def admit(index):
        try:
            jobs.enqueue(context, "scan", {"document_id": str(document["id"])}, str(index))
            return True
        except HTTPException as error:
            assert error.status_code == 429
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(admit, range(20))) == 5


def test_postgres_workers_claim_a_sandbox_job_only_once(pg_workflow):
    context, document, _, _ = pg_workflow
    jobs.enqueue(context, "scan", {"document_id": str(document["id"])}, "scan")
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: jobs.claim(sandbox=True), range(8)))
    assert sum(item is not None for item in claims) == 1


def test_postgres_recovery_after_rollback_does_not_reissue_paid_effect(pg_workflow, monkeypatch):
    _, session, command, sessions, storage = workflows.prepare_live_provider(pg_workflow, monkeypatch, "serpro_timestamp",
        {"consumer_key": "fake-key", "consumer_secret": "fake-secret"})
    calls = []
    def timestamp(pdf, *, credentials):
        calls.append(credentials)
        return pdf, {"provider": "test-double"}
    monkeypatch.setattr(serpro_timestamp_service, "apply_serpro_timestamp", timestamp)
    original_reserve = signing_service.reserve_storage
    monkeypatch.setattr(signing_service, "reserve_storage", lambda *args: (_ for _ in ()).throw(RuntimeError("crash before business commit")))
    with pytest.raises(RuntimeError):
        signing_service.sign_evidence(session["session_token"], False, command, ip_address="test", user_agent="test")
    monkeypatch.setattr(signing_service, "reserve_storage", original_reserve)
    with sessions() as db:
        operation = db.scalar(select(EnterpriseOperation))
        assert operation.status == "result_ready"
        assert db.scalar(select(EnterpriseSignature)) is None
        identity = operation.id
    def recover():
        return provider_operations.recover(sessions, lambda _: storage, identity)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: recover(), range(2)))
    assert results[0] == results[1] and len(calls) == 1
    with sessions() as db:
        assert len(list(db.scalars(select(EnterpriseSignature)))) == 1
        assert db.get(EnterpriseOperation, identity).encrypted_checkpoint is None


def test_postgres_late_owner_cannot_complete_reassigned_job(pg_workflow):
    context, document, _, _ = pg_workflow
    job = jobs.enqueue(context, "scan", {"document_id": str(document["id"])}, "scan")
    now = datetime.now(UTC)
    first = jobs.claim(sandbox=True, now=now)
    jobs.expire_leases(now=now+timedelta(minutes=5))
    jobs.retry_job(job["id"], context)
    second = jobs.claim(sandbox=True, now=now+timedelta(minutes=5))
    assert second["owner"] != first["owner"]
    assert not jobs.finish(first["id"], first["owner"], result={"late": True}, now=now)
    assert jobs.finish(second["id"], second["owner"], result={"ok": True}, now=now+timedelta(minutes=5))


def test_postgres_execution_migration_roundtrip(pg_workflow):
    _, _, sessions, _ = pg_workflow
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    migration = importlib.import_module("apps.core_api.alembic.versions.0041_enterprise_execution")
    engine = sessions.kw["bind"]
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
        assert connection.execute(text("SELECT count(*) FROM enterprise_jobs")).scalar() == 0


def test_postgres_audit_anonymization_requires_expired_purged_contract(pg_workflow):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError
    from core_api.modules.enterprise.completion_entity import EnterpriseClosure
    from core_api.modules.enterprise.lifecycle_entity import EnterpriseLifecycle
    from core_api.modules.signature_request.signature_request_entity import AuditEventEntity
    context, _, sessions, _ = pg_workflow
    engine = sessions.kw["bind"]
    immutable = importlib.import_module("apps.core_api.alembic.versions.0024_immutable_signature_records")
    closure = importlib.import_module("apps.core_api.alembic.versions.0040_enterprise_closure")
    with engine.begin() as connection:
        EnterpriseClosure.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            immutable.upgrade()
            closure.upgrade()
    statement = update(AuditEventEntity).where(AuditEventEntity.entity_id == context.tenant_id).values(actor_id="[erased]", metadata_sanitized={})
    with pytest.raises(DBAPIError), sessions.begin() as db:
        db.execute(statement)
    with sessions.begin() as db:
        db.add(EnterpriseLifecycle(tenant_id=context.tenant_id, status="purged", purged_at=datetime.now(UTC),
            recovery_until=datetime.now(UTC)-timedelta(days=1)))
    with sessions.begin() as db:
        assert db.execute(statement).rowcount > 0
    with pytest.raises(DBAPIError), sessions.begin() as db:
        db.execute(statement.values(action="enterprise.forged"))


def test_postgres_busy_tenant_does_not_block_another_tenant(pg_workflow):
    from core_api.modules.billing.billing_entity import BillingAccountEntity
    from core_api.modules.enterprise.entities import EnterpriseIntegration, EnterpriseCompartment
    from core_api.modules.enterprise.machine_context import MachineContext
    from core_api.modules.tenant.tenant_entity import TenantEntity
    context, document, sessions, _ = pg_workflow
    jobs.enqueue(context, "scan", {"document_id": str(document["id"])}, "busy")
    tenant, integration, compartment = uuid4(), uuid4(), uuid4()
    with sessions.begin() as db:
        db.add(TenantEntity(id=tenant, name="Other", slug="other"))
        db.flush()
        db.add(BillingAccountEntity(tenant_id=tenant, status="active", current_product_code="rubrica_enterprise"))
        db.add(EnterpriseIntegration(id=integration, tenant_id=tenant, name="Other", created_by="admin", environment="development", sandbox=True))
        db.flush()
        db.add(EnterpriseCompartment(id=compartment, integration_id=integration, name="Other"))
    other = jobs.enqueue(MachineContext(tenant, integration, compartment, "other", True), "scan", {"document_id": str(uuid4())}, "other")
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with sessions.begin() as db:
            db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == context.tenant_id).with_for_update())
            pending = pool.submit(jobs.claim, sandbox=True)
            assert pending.result(timeout=2)["id"] == other["id"]
    finally:
        pool.shutdown(wait=True)
