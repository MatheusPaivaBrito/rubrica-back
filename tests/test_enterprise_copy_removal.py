from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from botocore.exceptions import ClientError
from fastapi import HTTPException
import pytest
from sqlalchemy import select, func

from test_enterprise_storage import storage_db as make_storage_db
from core_api.modules.document.storage import R2DocumentStorage
from core_api.modules.enterprise import storage_access as access, storage_migration as migration, storage_removal as removal, storage_migration_router as routes
from core_api.modules.enterprise.entities import EnterpriseDocument, EnterpriseIntegration, EnterpriseRequest, EnterpriseSignature
from core_api.modules.enterprise.machine_context import MachineContext
from core_api.modules.enterprise.storage_entities import CopyRemoval, MigrationItem, MigrationDocument, StorageDestination, StorageMigration
from core_api.modules.enterprise.usage_entity import EnterpriseQuota, EnterpriseUsageEvent


class FakeDestination:
    configuration = {"prefix": "exports"}

    def __init__(self):
        self.objects = {}
        self.reads = 0

    def ensure_object(self, key, digest, size, content_type, source):
        with source() as stream:
            body = stream.read()
        assert len(body) == size and sha256(body).hexdigest() == digest
        self.objects.setdefault(key, body)

    def read_verified(self, key, digest, size):
        self.reads += 1
        body = self.objects.get(key)
        if body is None or len(body) != size or sha256(body).hexdigest() != digest:
            raise HTTPException(409, "External object integrity mismatch")
        return BytesIO(body)


@pytest.fixture
def exported(monkeypatch, tmp_path):
    env = make_storage_db.__wrapped__(monkeypatch, tmp_path)
    from core_api.modules.billing.billing_entity import BillingAccountEntity
    with env.sessions.begin() as db:
        db.add(BillingAccountEntity(tenant_id=env.tenant, current_product_code="rubrica_enterprise", status="active"))
    env.remote = FakeDestination()
    for module in (removal,):
        monkeypatch.setattr(module, "SessionLocal", env.sessions)
        monkeypatch.setattr(module, "configured_document_storage", lambda _: env.store)
    for module in (migration, removal, access):
        monkeypatch.setattr(module, "adapter_for", lambda _: env.remote)
    def export(kind="s3", signed=False):
        sandbox = kind != "s3"
        with env.sessions.begin() as db:
            db.get(EnterpriseIntegration, env.integration).sandbox = sandbox
            destination = StorageDestination(tenant_id=env.tenant, sandbox=sandbox, name="Customer", kind=kind,
                validated_at=datetime.now(UTC), created_by="admin")
            db.add(destination)
            db.flush()
            destination_id = destination.id
            document = db.get(EnterpriseDocument, env.document)
            total_size = document.size_bytes
            if signed:
                import json
                request = EnterpriseRequest(compartment_id=env.compartment, document_id=document.id, document_sha256=document.sha256,
                    idempotency_key="signed", payload_sha256="0" * 64, signers=[], status="completed",
                    expires_at=datetime.now(UTC) + timedelta(days=1), token_public_id="token")
                db.add(request)
                db.flush()
                content, evidence = b"%PDF-signed", {"signed": True}
                digest = sha256(content).hexdigest()
                key, size = env.store.put(BytesIO(content), filename="signed.pdf", sha256=digest, scope="tenant")
                db.add(EnterpriseSignature(request_id=request.id, signer_id=uuid4(), signed_at=datetime.now(UTC),
                    artifact_storage_key=key, artifact_sha256=digest, artifact_size=size, evidence=evidence,
                    evidence_sha256=sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), evidence_hmac="0" * 64))
                total_size += size
            quota = db.scalar(select(EnterpriseQuota))
            if quota is None:
                db.add(EnterpriseQuota(tenant_id=env.tenant, sandbox=sandbox, storage_bytes=total_size, document_count=1))
        job_id = routes.start_migration(env.tenant, env.integration, routes.MigrationCreate(
            destination_id=destination_id, acknowledge_plaintext_export=True), env.context)["id"]
        migration.migrate_once()
        if kind == "independent":
            with env.sessions.begin() as db:
                for item in db.scalars(select(MigrationItem)):
                    item.status, item.downloaded_at, item.verified_at = "verified", datetime.now(UTC), datetime.now(UTC)
            migration.migrate_once()
        env.job = job_id
        env.machine = MachineContext(env.tenant, env.integration, env.compartment, "token", sandbox)
        return env
    return export


def schedule(env):
    return routes.request_copy_removal(env.tenant, env.integration, env.job, routes.RemovalRequest(
        document_ids=[env.document], confirm_remove_rubrica_copies=True, acknowledge_independent_unavailability=True), env.context)


def test_scheduling_is_durable_idempotent_and_does_not_remove_immediately(exported):
    env = exported()
    assert schedule(env)["scheduled_copies"] == 1
    assert schedule(env)["scheduled_copies"] == 0
    with env.sessions() as db:
        document = db.get(EnterpriseDocument, env.document)
        assert document.rubrica_copy_deleted_at is None
        with env.store.get(document.storage_key) as stream:
            assert stream.read() == b"%PDF-test"
        assert db.scalar(select(CopyRemoval)).status == "pending"


def test_s3_removal_rechecks_target_decrements_once_and_preserves_metadata(exported):
    env = exported()
    before = env.remote.reads
    schedule(env)
    assert removal.remove_once()
    assert env.remote.reads > before
    assert not removal.remove_once()
    with env.sessions() as db:
        document = db.get(EnterpriseDocument, env.document)
        assert document.rubrica_copy_deleted_at is not None
        assert document.deleted_at is None and document.filename == "a.pdf"
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0
        assert db.scalar(select(EnterpriseQuota)).document_count == 0
        assert db.scalar(select(func.count()).select_from(EnterpriseUsageEvent).where(EnterpriseUsageEvent.kind == "storage.removed")) == 1
        with pytest.raises(FileNotFoundError):
            env.store.get(document.storage_key)
        with access.open_copy(db, env.machine, "original", document) as content:
            assert content.read() == b"%PDF-test"


@pytest.mark.parametrize("failure", ["missing", "hash", "403"])
def test_changed_or_unavailable_destination_never_causes_source_removal(exported, monkeypatch, failure):
    env = exported()
    schedule(env)
    if failure == "missing":
        env.remote.objects.clear()
    elif failure == "hash":
        for key in env.remote.objects:
            env.remote.objects[key] = b"corrupted"
    else:
        monkeypatch.setattr(env.remote, "read_verified", lambda *args: (_ for _ in ()).throw(HTTPException(403, "private")))
    removal.remove_once()
    with env.sessions() as db:
        intent = db.scalar(select(CopyRemoval))
        assert intent.status == "retry" and intent.error_code == "removal_not_confirmed"
        assert intent.next_attempt_at > datetime.now(UTC).replace(tzinfo=None)
        document = db.get(EnterpriseDocument, env.document)
        assert document.rubrica_copy_deleted_at is None
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == document.size_bytes
        with env.store.get(document.storage_key) as stream:
            assert stream.read() == b"%PDF-test"


def test_bucket_lock_never_reduces_storage_meter(exported, monkeypatch):
    env = exported()
    schedule(env)
    monkeypatch.setattr(env.store, "remove_copy", lambda key: (_ for _ in ()).throw(PermissionError("bucket lock")))
    removal.remove_once()
    with env.sessions() as db:
        assert db.scalar(select(CopyRemoval)).status == "retry"
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 9
        assert db.scalar(select(EnterpriseUsageEvent).where(EnterpriseUsageEvent.kind == "storage.removed")) is None


def test_crash_after_physical_removal_can_read_external_and_retry_without_double_charge(exported):
    env = exported()
    schedule(env)
    with pytest.raises(RuntimeError):
        with env.sessions.begin() as db:
            intent = db.scalar(select(CopyRemoval))
            removal.process_removal(db, intent)
            db.flush()
            raise RuntimeError("simulated crash before commit")
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 9
        document = db.get(EnterpriseDocument, env.document)
        assert document.rubrica_copy_deleted_at is None
        with access.open_copy(db, env.machine, "original", document, storage_factory=lambda _: env.store) as content:
            assert content.read() == b"%PDF-test"
    assert removal.remove_once()
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0
        assert db.scalar(select(func.count()).select_from(EnterpriseUsageEvent).where(EnterpriseUsageEvent.kind == "storage.removed")) == 1


def test_independent_removal_requires_additional_confirmation_and_returns_410(exported):
    env = exported("independent")
    with pytest.raises(HTTPException) as error:
        routes.request_copy_removal(env.tenant, env.integration, env.job, routes.RemovalRequest(
            document_ids=[env.document], confirm_remove_rubrica_copies=True), env.context)
    assert error.value.status_code == 422
    schedule(env)
    removal.remove_once()
    with env.sessions() as db:
        document = db.get(EnterpriseDocument, env.document)
        with pytest.raises(HTTPException) as error:
            access.open_copy(db, env.machine, "original", document)
        assert error.value.status_code == 410


def test_open_requests_block_removal_even_when_old_migration_is_complete(exported):
    env = exported()
    with env.sessions.begin() as db:
        document = db.get(EnterpriseDocument, env.document)
        db.add(EnterpriseRequest(compartment_id=env.compartment, document_id=document.id, document_sha256=document.sha256,
            idempotency_key="new", payload_sha256="0" * 64, signers=[], status="open", expires_at=datetime.now(UTC) + timedelta(days=1), token_public_id="token"))
    with pytest.raises(HTTPException) as error:
        schedule(env)
    assert error.value.status_code == 409
    with env.sessions() as db:
        assert db.scalar(select(CopyRemoval)) is None


def test_request_cannot_start_while_copy_removal_is_pending_or_done(exported):
    env = exported()
    schedule(env)
    with env.sessions() as db:
        with pytest.raises(HTTPException):
            access.ensure_signable_copy(db, db.get(EnterpriseDocument, env.document))
    removal.remove_once()
    with env.sessions() as db:
        with pytest.raises(HTTPException):
            access.ensure_signable_copy(db, db.get(EnterpriseDocument, env.document))


@pytest.mark.parametrize("change", ["tenant", "integration", "compartment", "mode"])
def test_external_access_cannot_cross_binding(exported, change):
    env = exported()
    schedule(env)
    removal.remove_once()
    changes = {"tenant": {"tenant_id": uuid4()}, "integration": {"integration_id": uuid4()},
               "compartment": {"compartment_id": uuid4()}, "mode": {"sandbox": True}}
    with env.sessions() as db:
        with pytest.raises(HTTPException) as error:
            access.open_copy(db, replace(env.machine, **changes[change]), "original", db.get(EnterpriseDocument, env.document))
    assert error.value.status_code == 404


def test_restore_reencrypts_new_copy_adds_meter_once_and_allows_new_requests(exported):
    env = exported()
    schedule(env)
    removal.remove_once()
    with env.sessions() as db:
        old_key = db.get(EnterpriseDocument, env.document).storage_key
    payload = routes.RestoreRequest(document_ids=[env.document])
    assert routes.restore_copies(env.tenant, env.integration, env.job, payload, env.context)["restored_copies"] == 1
    assert routes.restore_copies(env.tenant, env.integration, env.job, payload, env.context)["restored_copies"] == 0
    with env.sessions() as db:
        document = db.get(EnterpriseDocument, env.document)
        assert document.storage_key != old_key and document.rubrica_copy_deleted_at is None
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 9
        assert db.scalar(select(EnterpriseQuota)).document_count == 1
        access.ensure_signable_copy(db, document)
        with env.store.get(document.storage_key) as content:
            assert content.read() == b"%PDF-test"
        assert db.scalar(select(func.count()).select_from(EnterpriseUsageEvent).where(EnterpriseUsageEvent.kind == "storage.added")) == 1
    # Another explicit deletion is a new copy generation, not a duplicate debit.
    assert schedule(env)["scheduled_copies"] == 1
    removal.remove_once()
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0
        assert len(list(db.scalars(select(CopyRemoval)))) == 2


def test_restore_during_pending_removal_is_rejected(exported):
    env = exported()
    schedule(env)
    with pytest.raises(HTTPException) as error:
        routes.restore_copies(env.tenant, env.integration, env.job, routes.RestoreRequest(document_ids=[env.document]), env.context)
    assert error.value.status_code == 409


def test_missing_external_source_rolls_back_restoration_meter(exported):
    env = exported()
    schedule(env)
    removal.remove_once()
    env.remote.objects.clear()
    with pytest.raises(HTTPException):
        routes.restore_copies(env.tenant, env.integration, env.job, routes.RestoreRequest(document_ids=[env.document]), env.context)
    with env.sessions() as db:
        assert db.get(EnterpriseDocument, env.document).rubrica_copy_deleted_at is not None
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0


def test_wrong_job_cannot_schedule_removal(exported):
    env = exported()
    with pytest.raises(HTTPException) as error:
        routes.request_copy_removal(uuid4(), env.integration, env.job, routes.RemovalRequest(
            document_ids=[env.document], confirm_remove_rubrica_copies=True), env.context)
    assert error.value.status_code == 404


@pytest.mark.parametrize("delete_error,head", [(True, "missing"), (False, "403"), (False, "exists")])
def test_strict_r2_deletion_never_swallows_denial_or_false_success(delete_error, head):
    def delete(**kwargs):
        if delete_error:
            raise ClientError({"Error": {"Code": "AccessDenied"}, "ResponseMetadata": {"HTTPStatusCode": 403}}, "DeleteObject")
    def check(**kwargs):
        if head != "exists":
            status = 403 if head == "403" else 404
            raise ClientError({"Error": {"Code": str(status)}, "ResponseMetadata": {"HTTPStatusCode": status}}, "HeadObject")
        return {}
    store = object.__new__(R2DocumentStorage)
    store.client, store.bucket, store.prefix = SimpleNamespace(delete_object=delete, head_object=check), "bucket", "prefix"
    with pytest.raises((ClientError, OSError)):
        store.remove_copy("tenants/document")


def test_strict_r2_deletion_confirms_404():
    calls = []
    def head(**kwargs):
        calls.append(kwargs)
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")
    store = object.__new__(R2DocumentStorage)
    store.client, store.bucket, store.prefix = SimpleNamespace(delete_object=lambda **kwargs: calls.append(kwargs), head_object=head), "bucket", "prefix"
    store.remove_copy("tenants/document")
    assert calls == [{"Bucket": "bucket", "Key": "prefix/tenants/document"}] * 2


def test_signed_artifacts_are_removed_and_read_externally_without_losing_evidence(exported):
    env = exported(signed=True)
    assert schedule(env)["scheduled_copies"] == 2
    removal.remove_once()
    removal.remove_once()
    with env.sessions() as db:
        signature = db.scalar(select(EnterpriseSignature))
        assert signature.rubrica_copy_deleted_at is not None and signature.evidence == {"signed": True}
        with access.open_copy(db, env.machine, "artifact", signature) as content:
            assert content.read() == b"%PDF-signed"
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0
        assert len(list(db.scalars(select(MigrationItem)))) == 3  # Evidence stays as metadata + exported JSON.
        from core_api.modules.enterprise.usage_router import canonical_summary
        assert canonical_summary(db, env.machine)["storage_bytes"] == 0


def test_partial_restore_failure_removes_new_objects_and_rolls_back_all_counters(exported, monkeypatch):
    env = exported(signed=True)
    schedule(env)
    removal.remove_once()
    removal.remove_once()
    from core_api.modules.enterprise import storage_removal
    original = storage_removal.external_content
    def content(db, context, kind, record):
        if kind == "artifact":
            raise HTTPException(502, "unavailable")
        return original(db, context, kind, record)
    monkeypatch.setattr(storage_removal, "external_content", content)
    before = set(path for path in env.store.root.rglob("*") if path.is_file())
    with pytest.raises(HTTPException):
        routes.restore_copies(env.tenant, env.integration, env.job, routes.RestoreRequest(document_ids=[env.document]), env.context)
    assert {path for path in env.store.root.rglob("*") if path.is_file()} == before
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0
        assert db.get(EnterpriseDocument, env.document).rubrica_copy_deleted_at is not None
        assert db.scalar(select(EnterpriseUsageEvent).where(EnterpriseUsageEvent.kind == "storage.added")) is None


def test_worker_rechecks_requests_opened_after_scheduling(exported):
    env = exported()
    schedule(env)
    with env.sessions.begin() as db:
        document = db.get(EnterpriseDocument, env.document)
        db.add(EnterpriseRequest(compartment_id=env.compartment, document_id=document.id, document_sha256=document.sha256,
            idempotency_key="unexpected", payload_sha256="0" * 64, signers=[], status="open", expires_at=datetime.now(UTC) + timedelta(days=1), token_public_id="token"))
    removal.remove_once()
    with env.sessions() as db:
        assert db.scalar(select(CopyRemoval)).status == "retry"
        assert db.get(EnterpriseDocument, env.document).rubrica_copy_deleted_at is None
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 9


def test_counter_mismatch_prevents_physical_deletion(exported):
    env = exported()
    schedule(env)
    with env.sessions.begin() as db:
        db.scalar(select(EnterpriseQuota)).storage_bytes = 0
    removal.remove_once()
    with env.sessions() as db:
        document = db.get(EnterpriseDocument, env.document)
        assert document.rubrica_copy_deleted_at is None
        with env.store.get(document.storage_key) as content:
            assert content.read() == b"%PDF-test"


def test_local_corruption_is_not_silently_hidden_by_external_fallback(exported):
    env = exported()
    with env.sessions() as db:
        document = db.get(EnterpriseDocument, env.document)
        path = env.store.root / document.storage_key
        path.chmod(0o600)
        path.write_bytes(b"corrupted")
        before = env.remote.reads
        with pytest.raises(HTTPException) as error:
            access.open_copy(db, env.machine, "original", document, storage_factory=lambda _: env.store)
        assert error.value.status_code == 409 and env.remote.reads == before


def test_independent_storage_cannot_be_restored_without_an_accessible_source(exported):
    env = exported("independent")
    schedule(env)
    removal.remove_once()
    with pytest.raises(HTTPException) as error:
        routes.restore_copies(env.tenant, env.integration, env.job, routes.RestoreRequest(document_ids=[env.document]), env.context)
    assert error.value.status_code == 410
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0


def test_new_verified_receipt_can_explicitly_recover_an_old_pending_intent(exported):
    env = exported()
    schedule(env)
    with env.sessions.begin() as db:
        intent = db.scalar(select(CopyRemoval))
        original_intent_id = intent.id
        old_receipt = db.get(MigrationItem, intent.migration_item_id)
        old_job = db.get(StorageMigration, env.job)
        fresh_job = StorageMigration(tenant_id=env.tenant, integration_id=env.integration, destination_id=old_job.destination_id,
            status="completed", created_by="admin", export_acknowledged_at=datetime.now(UTC))
        db.add(fresh_job)
        db.flush()
        db.add(MigrationDocument(migration_id=fresh_job.id, document_id=env.document, status="verified"))
        fresh_receipt = MigrationItem(migration_id=fresh_job.id, document_id=env.document, source_kind="original", source_id=env.document,
            sha256=old_receipt.sha256, size_bytes=old_receipt.size_bytes, target_key=old_receipt.target_key,
            status="verified", verified_at=datetime.now(UTC))
        db.add(fresh_receipt)
        db.flush()
        fresh_job_id, fresh_receipt_id = fresh_job.id, fresh_receipt.id
        intent.status, intent.next_attempt_at = "retry", datetime.now(UTC) + timedelta(days=1)
    env.job = fresh_job_id
    assert schedule(env)["scheduled_copies"] == 1
    with env.sessions() as db:
        intent = db.get(CopyRemoval, original_intent_id)
        assert intent.migration_item_id == fresh_receipt_id
        assert db.scalar(select(func.count()).select_from(CopyRemoval)) == 1
    assert removal.remove_once()
    with env.sessions() as db:
        assert db.scalar(select(EnterpriseQuota)).storage_bytes == 0


def test_removal_schema_roundtrip_does_not_mutate_existing_document_rows():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa
    path = Path(__file__).parents[1] / "apps/core_api/alembic/versions/0038_enterprise_copy_removal.py"
    spec = importlib.util.spec_from_file_location("copy_removal_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(sa.text("CREATE TABLE enterprise_documents (id TEXT PRIMARY KEY, storage_key TEXT NOT NULL)"))
        db.execute(sa.text("INSERT INTO enterprise_documents VALUES ('document', 'preserved-key')"))
        with Operations.context(MigrationContext.configure(db)):
            module.upgrade()
            assert "enterprise_copy_removals" in sa.inspect(db).get_table_names()
            module.downgrade()
        assert db.scalar(sa.text("SELECT storage_key FROM enterprise_documents")) == "preserved-key"
