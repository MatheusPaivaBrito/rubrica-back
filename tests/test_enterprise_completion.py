from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from test_enterprise_lifecycle import contract_db as make_contract_db, NOW, suspend
from core_api.modules.enterprise import backup_barrier, closure, lifecycle_router, retention
from core_api.modules.enterprise.completion_entity import EnterpriseClosure
from core_api.modules.enterprise.entities import EnterpriseDocument, EnterpriseIntegration, EnterpriseProvider
from core_api.modules.enterprise.lifecycle_entity import EnterpriseLifecycle


@pytest.fixture
def closed(monkeypatch, tmp_path):
    env = make_contract_db.__wrapped__(monkeypatch, tmp_path)
    monkeypatch.setattr(closure, "SessionLocal", env.sessions)
    monkeypatch.setattr(backup_barrier, "SessionLocal", env.sessions)
    monkeypatch.setattr(closure, "configured_document_storage", lambda _: env.store)
    monkeypatch.setattr(closure.settings, "CORE_INTERNAL_SERVICE_KEY", "test-internal-key")
    monkeypatch.setattr(closure.settings, "ENTERPRISE_BACKUP_POLICY", "external")
    monkeypatch.setattr(closure.settings, "ENTERPRISE_BACKUP_REPOSITORIES", "a" * 64)
    def accepted(url, **kwargs):
        return SimpleNamespace(status_code=200, json=lambda: {"operation_id": kwargs["json"]["operation_id"], "retired": True})
    monkeypatch.setattr(closure.httpx, "post", accepted)
    suspend(env)
    retention.synchronize_once(now=NOW + timedelta(days=30))
    retention.purge_once(now=NOW + timedelta(days=30))
    retention.synchronize_once(now=NOW + timedelta(days=30))
    return env


def test_closure_erases_creators_provider_secrets_and_stray_objects_without_touching_interactive_storage(closed):
    env = closed
    with env.sessions.begin() as db:
        db.add(EnterpriseProvider(tenant_id=env.tenant, sandbox=False, provider="serproid", encrypted_configuration="fake-sensitive",
            updated_by="person@example.test"))
    orphan_key, _ = env.store.put(__import__("io").BytesIO(b"orphan"), filename="x", scope=f"tenants/{env.tenant}/enterprise/live/orphan")
    interactive, _ = env.store.put(__import__("io").BytesIO(b"retained"), filename="x", scope=f"tenants/{env.tenant}/accounts/interactive")
    assert closure.finalize_once(now=NOW + timedelta(days=30))
    with env.sessions() as db:
        item = db.scalar(select(EnterpriseClosure))
        assert item.objects_verified_at and item.metadata_purged_at and item.credentials_retired_at
        assert not closure.complete(item)  # No optimistic backup guarantee.
        provider = db.scalar(select(EnterpriseProvider))
        assert provider.encrypted_configuration == "" and provider.updated_by == "[erased]"
        assert db.get(EnterpriseIntegration, env.integration).deleted_at
        assert db.get(EnterpriseDocument, env.document).filename == "[removed]"
    with pytest.raises(FileNotFoundError):
        env.store.get(orphan_key)
    with env.store.get(interactive) as stream:
        assert stream.read() == b"retained"


def receipt(**overrides):
    values = dict(environment="development", repository_identity="a" * 64, snapshot_id="b" * 64,
        snapshot_started_at=NOW + timedelta(days=30, minutes=1), oldest_retained_snapshot_at=NOW + timedelta(days=30, minutes=1),
        compacted_and_checked=True, local_archives_removed=True, current_objects_verified=True)
    return backup_barrier.BackupReceipt(**(values | overrides))


@pytest.mark.parametrize("override", [{"repository_identity": "f" * 64}, {"environment": "production"},
    {"oldest_retained_snapshot_at": NOW}, {"local_archives_removed": False}, {"current_objects_verified": False}])
def test_backup_proof_rejects_incomplete_or_wrong_inventory(closed, override):
    env = closed
    closure.finalize_once(now=NOW + timedelta(days=30))
    with env.sessions.begin() as db:
        with pytest.raises(HTTPException):
            backup_barrier.acknowledge(db, db.scalar(select(EnterpriseClosure)), receipt(**override), now=NOW + timedelta(days=31))


def test_all_registered_repositories_must_acknowledge_before_reopening(closed, monkeypatch):
    env = closed
    closure.finalize_once(now=NOW + timedelta(days=30))
    monkeypatch.setattr(closure.settings, "ENTERPRISE_BACKUP_REPOSITORIES", "a" * 64 + "," + "c" * 64)
    with env.sessions.begin() as db:
        item = db.scalar(select(EnterpriseClosure))
        assert not backup_barrier.acknowledge(db, item, receipt(), now=NOW + timedelta(days=31))["complete"]
        assert backup_barrier.acknowledge(db, item, receipt(repository_identity="c" * 64), now=NOW + timedelta(days=31))["complete"]
        assert closure.complete(item)


def test_auth_retirement_failure_is_retried_without_restoring_metadata(closed, monkeypatch):
    env = closed
    monkeypatch.setattr(closure.httpx, "post", lambda *a, **k: SimpleNamespace(status_code=503))
    closure.finalize_once(now=NOW + timedelta(days=30))
    with env.sessions() as db:
        item = db.scalar(select(EnterpriseClosure))
        assert item.metadata_purged_at and not item.credentials_retired_at and item.error_code == "auth_retirement_pending"


def test_recontract_is_explicit_empty_and_idempotent_after_verified_closure(closed):
    from core_api.modules.billing.billing_entity import BillingAccountEntity
    env = closed
    closure.finalize_once(now=NOW + timedelta(days=30))
    with env.sessions.begin() as db:
        item = db.scalar(select(EnterpriseClosure))
        identity = item.id
        backup_barrier.acknowledge(db, item, receipt(), now=NOW + timedelta(days=31))
        db.scalar(select(BillingAccountEntity)).cancel_at_period_end = False
    payload = lifecycle_router.RecontractRequest(closure_id=identity, confirm_empty_contract=True)
    result = lifecycle_router.reopen_contract(env.tenant, payload, env.context)
    assert result["new_tokens_required"] and not result["data_restored"]
    assert lifecycle_router.reopen_contract(env.tenant, payload, env.context)["status"] == "already_reopened"
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseLifecycle)).status == "active"
        assert db.get(EnterpriseDocument, env.document).status == "purged"


def test_backup_receipts_require_internal_service_identity(closed):
    for identity, key in (("core_api", "test-internal-key"), ("retention_worker", "wrong"), ("", "")):
        with pytest.raises(HTTPException):
            backup_barrier.require_backup_worker(identity, key)
    backup_barrier.require_backup_worker("retention_worker", "test-internal-key")


def test_auth_retirement_is_idempotent_and_does_not_revoke_a_new_contract_token():
    from auth_api.modules.machine_credentials.entity import MachineCredentialEntity, MachineCredentialAuditEntity, MachineRetirementEntity
    from auth_api.modules.machine_credentials.router import RetirementRequest, retire_credentials
    from auth_api.modules.machine_credentials.service import authenticate_token, rotate_token, CredentialError
    engine = create_engine("sqlite://")
    for model in (MachineCredentialEntity, MachineCredentialAuditEntity, MachineRetirementEntity):
        model.__table__.create(engine)
    sessions = sessionmaker(engine)
    tenant, integration, operation = uuid4(), uuid4(), uuid4()
    with sessions.begin() as db:
        db.add(MachineCredentialEntity(tenant_id=tenant, integration_id=integration, environment="development", sandbox=True))
        db.flush()
        old = rotate_token(db, tenant_id=tenant, integration_id=integration, subject="admin", environment="development", sandbox=True,
            scopes=frozenset({"documents:create"}), expires_at=None, now=NOW)
    request = RetirementRequest(tenant_id=tenant, environment="development", operation_id=operation)
    with sessions.begin() as db:
        retire_credentials(db, request)
    with sessions.begin() as db:
        with pytest.raises(CredentialError):
            authenticate_token(db, secret=old.secret, environment="development", sandbox=True, permission="documents:create", now=NOW)
        new = rotate_token(db, tenant_id=tenant, integration_id=integration, subject="admin", environment="development", sandbox=True,
            scopes=frozenset({"documents:create"}), expires_at=None, now=NOW)
    with sessions.begin() as db:
        retire_credentials(db, request)
        assert authenticate_token(db, secret=new.secret, environment="development", sandbox=True, permission="documents:create", now=NOW)


def test_public_schema_contains_no_admin_or_internal_contracts():
    from core_api.bootstrap.app import create_app
    from core_api.modules.enterprise.developer_portal import public_schema, sample_pdf
    schema = public_schema(create_app())
    assert schema["paths"] and all(path.startswith("/api/v1/") for path in schema["paths"])
    assert "/enterprise/tenants/{tenant_id}/integrations/{integration_id}/token" not in schema["paths"]
    assert "client_secret" not in json.dumps(schema)
    assert sample_pdf().startswith(b"%PDF-")
    assert schema["paths"]["/api/v1/sandbox/signing-session"]["get"]["security"] == [{"SignerSession": []}]


def test_backup_history_checks_archive_age_not_only_upload_time(tmp_path):
    from toolbox.operations.enterprise_backup_barrier import obsolete_snapshots, managed_archives
    barrier = datetime(2026, 11, 1, tzinfo=UTC)
    old = {"id": "a" * 64, "tags": ["rubrica-production"], "time": "2026-11-04T00:00:00Z", "paths": ["/backups/20261001T000000Z"]}
    fresh = old | {"id": "b" * 64, "paths": ["/backups/20261104T000000Z"]}
    assert obsolete_snapshots([old, fresh], barrier, "rubrica-production") == ["a" * 64]
    archive = tmp_path / "20261001T000000Z"
    archive.mkdir()
    (archive / "manifest.txt").write_text("compose_project=rubrica\n")
    (archive / "SHA256SUMS").write_text(sha256(b"x").hexdigest())
    assert managed_archives(tmp_path, barrier) == [archive]
    with pytest.raises(ValueError):
        obsolete_snapshots([old | {"tags": ["other-project"]}], barrier, "rubrica-production")


def test_closure_erases_queued_job_secrets_and_results(closed):
    from core_api.modules.enterprise.execution_entity import EnterpriseJob
    env = closed
    with env.sessions.begin() as db:
        job = EnterpriseJob(tenant_id=env.tenant, integration_id=env.integration, compartment_id=uuid4(),
            sandbox=False, kind="sign", dedup_key="e" * 64, encrypted_payload="sealed-consent", result={"personal": "data"})
        db.add(job)
        db.flush()
        identity = job.id
    assert closure.finalize_once(now=NOW+timedelta(days=30))
    with env.sessions() as db:
        item = db.get(EnterpriseJob, identity)
        assert item.status == "erased" and item.encrypted_payload is None and item.result is None
