from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import core_api.infrastructure.database.loader  # noqa: F401
from core_api.infrastructure.database.connection import Base
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.document.storage import LocalDocumentStorage
from core_api.modules.enterprise import s3_destination as s3, storage_calculator as calculator, storage_migration as migration, storage_migration_router as routes, storage_router as destinations
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseDocument, EnterpriseIntegration, EnterpriseRequest
from core_api.modules.enterprise.storage_entities import MigrationDocument, MigrationItem, StorageDestination, StorageMigration
from core_api.modules.enterprise.usage_entity import EnterpriseQuota


def configuration():
    return dict(endpoint="https://s3.amazonaws.com", bucket="customer-bucket", region="us-east-1",
                prefix="exports", access_key_id="test-access-key", secret_access_key="test-secret")


@pytest.mark.parametrize("endpoint", ["http://s3.amazonaws.com", "https://s3.amazonaws.com:8443", "https://user@s3.amazonaws.com",
    "https://s3.amazonaws.com/path", "https://s3.amazonaws.com/?secret=x", "https://s3.amazonaws.com/#x",
    "https://127.0.0.1", "https://169.254.169.254", "https://s3.amazonaws.com.attacker.org", "https://s3.amazonaws.com:wrong"])
def test_reject_unsafe_endpoint(endpoint):
    with pytest.raises(HTTPException):
        s3.endpoint_host(endpoint)


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["169.254.169.254"], ["10.0.0.1"], ["::1"], ["8.8.8.8", "10.1.2.3"], []])
def test_dns_rejects_private_and_mixed_answers(monkeypatch, addresses):
    monkeypatch.setattr(s3.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", (address, 443)) for address in addresses])
    with pytest.raises(HTTPException):
        s3.pinned_address("s3.amazonaws.com")


def test_pinned_connection_preserves_sigv4_host_and_tls_hostname(monkeypatch):
    monkeypatch.setattr(s3, "pinned_address", lambda _: "8.8.8.8")
    url, headers, extensions = s3.S3Destination(configuration()).signed_request("PUT", "folder/a b.pdf", digest=sha256(b"pdf").hexdigest(), size=3)
    assert url == "https://8.8.8.8/customer-bucket/folder/a%20b.pdf"
    assert headers["Host"] == "s3.amazonaws.com"
    assert headers["If-None-Match"] == "*"
    assert "Credential=test-access-key/" in headers["Authorization"]
    assert extensions == {"sni_hostname": "s3.amazonaws.com"}


def client_mock(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(s3.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(s3, "pinned_address", lambda _: "8.8.8.8")


@pytest.mark.parametrize("body,status", [(b"wrong", 200), (b"pdf-too-large", 200), (b"", 302), (b"", 403)])
def test_remote_mismatch_or_redirect_never_returns_content(monkeypatch, body, status):
    client_mock(monkeypatch, lambda _: httpx.Response(status, stream=httpx.ByteStream(body), headers={"Location": "http://127.0.0.1"}))
    with pytest.raises(HTTPException):
        s3.S3Destination(configuration()).read_verified("a.pdf", sha256(b"pdf").hexdigest(), 3)


def test_copy_checks_after_put_and_retry_never_overwrites(monkeypatch):
    stored, calls = {}, []
    def handler(request):
        calls.append(request.method)
        assert request.headers["host"] == "s3.amazonaws.com"
        if request.method == "GET":
            return httpx.Response(200, stream=httpx.ByteStream(stored["body"])) if "body" in stored else httpx.Response(404)
        assert request.method == "PUT" and request.headers["if-none-match"] == "*"
        stored["body"] = request.read()
        return httpx.Response(200)
    client_mock(monkeypatch, handler)
    adapter = s3.S3Destination(configuration())
    adapter.ensure_object("file", sha256(b"pdf").hexdigest(), 3, "application/pdf", lambda: BytesIO(b"pdf"))
    assert calls == ["GET", "PUT", "GET"]
    adapter.ensure_object("file", sha256(b"pdf").hexdigest(), 3, "application/pdf", lambda: pytest.fail("must not read source twice"))
    assert calls == ["GET", "PUT", "GET", "GET"]
    with pytest.raises(ValueError):
        adapter.delete_probe("customer/file.pdf")


@pytest.fixture
def storage_db(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    store = LocalDocumentStorage(tmp_path)
    for module in (destinations, routes, migration, calculator):
        monkeypatch.setattr(module, "SessionLocal", sessions)
    monkeypatch.setattr(destinations, "require_enterprise", lambda *a: None)
    monkeypatch.setattr(destinations.tenant_service, "_audit", lambda *a: None)
    monkeypatch.setattr(routes, "binding", lambda db, tenant, integration, context: db.get(EnterpriseIntegration, integration))
    monkeypatch.setattr(migration, "configured_document_storage", lambda _: store)
    monkeypatch.setattr(migration.settings, "ENVIRONMENT", "development")
    tenant, integration, compartment = uuid4(), uuid4(), uuid4()
    key, size = store.put(BytesIO(b"%PDF-test"), filename="a.pdf", sha256=sha256(b"%PDF-test").hexdigest(), scope="tenant")
    with sessions.begin() as db:
        db.add(EnterpriseIntegration(id=integration, tenant_id=tenant, name="ERP", environment="development", sandbox=True, created_by="admin"))
        db.add(EnterpriseCompartment(id=compartment, integration_id=integration, name="Customer"))
        document = EnterpriseDocument(compartment_id=compartment, filename="a.pdf", sha256=sha256(b"%PDF-test").hexdigest(), size_bytes=size,
            storage_key=key, status="ready", token_public_id="token", idempotency_key="upload")
        db.add(document)
        db.flush()
        document_id = document.id
    return SimpleNamespace(sessions=sessions, tenant=tenant, integration=integration, compartment=compartment,
                           document=document_id, store=store, context=SimpleNamespace(subject="admin"))


def test_destination_credentials_encrypted_and_tenant_mode_bound(storage_db):
    env = storage_db
    payload = destinations.DestinationCreate(name="Customer", kind="s3", configuration=configuration())
    result = destinations.create_destination(env.tenant, payload, False, env.context)
    assert "configuration" not in result and "test-secret" not in str(result)
    with env.sessions() as db:
        item = destinations.destination_for(db, env.tenant, result["id"], False)
        assert "test-secret" not in item.encrypted_configuration
        assert destinations.adapter_for(item).configuration["secret_access_key"] == "test-secret"
        item.tenant_id = uuid4()
        with pytest.raises(InvalidTag):
            destinations.adapter_for(item)
        with pytest.raises(HTTPException):
            destinations.destination_for(db, env.tenant, result["id"], True)
        with pytest.raises(HTTPException):
            destinations.destination_for(db, uuid4(), result["id"], False)
    with pytest.raises(HTTPException):
        destinations.create_destination(env.tenant, payload, True, env.context)


def start(env, kind="independent"):
    dest = destinations.create_destination(env.tenant, destinations.DestinationCreate(name="Destination", kind=kind), True, env.context)
    return routes.start_migration(env.tenant, env.integration,
        routes.MigrationCreate(destination_id=dest["id"], acknowledge_plaintext_export=True), env.context)["id"]


def test_export_acknowledgement_is_mandatory_and_unverified_destinations_blocked(storage_db):
    env = storage_db
    result = destinations.create_destination(env.tenant, destinations.DestinationCreate(name="NAS", kind="independent"), True, env.context)
    with pytest.raises(HTTPException):
        routes.start_migration(env.tenant, env.integration,
            routes.MigrationCreate(destination_id=result["id"], acknowledge_plaintext_export=False), env.context)
    with env.sessions.begin() as db:
        db.get(StorageDestination, result["id"]).validated_at = None
    with pytest.raises(HTTPException):
        routes.start_migration(env.tenant, env.integration,
            routes.MigrationCreate(destination_id=result["id"], acknowledge_plaintext_export=True), env.context)


@pytest.mark.parametrize("status", ["draft", "open", "cancelled", "expired", "completed"])
def test_open_requests_wait_terminal_requests_migrate_and_source_is_preserved(storage_db, status):
    env = storage_db
    with env.sessions.begin() as db:
        document = db.get(EnterpriseDocument, env.document)
        db.add(EnterpriseRequest(compartment_id=env.compartment, document_id=env.document, document_sha256=document.sha256,
            idempotency_key="request", payload_sha256="0" * 64, signers=[], status=status,
            expires_at=datetime.now(UTC) + timedelta(days=1), token_public_id="token"))
    job_id = start(env, "rubrica")
    assert migration.migrate_once()
    with env.sessions() as db:
        entry = db.scalar(select(MigrationDocument))
        if status in {"draft", "open"}:
            assert entry.status == "waiting_signature"
            assert db.scalar(select(MigrationItem)) is None
            assert db.get(StorageMigration, job_id).status == "pending"
        else:
            assert entry.status == "verified"
            assert db.get(StorageMigration, job_id).status == "completed"
        document = db.get(EnterpriseDocument, env.document)
        with env.store.get(document.storage_key) as content:
            assert content.read() == b"%PDF-test"
        assert document.rubrica_copy_deleted_at is None


def test_independent_delivery_requires_finished_download_and_matching_receipt(storage_db, monkeypatch):
    env = storage_db
    job_id = start(env)
    migration.migrate_once()
    with env.sessions() as db:
        item = db.scalar(select(MigrationItem))
        item_id, digest, size = item.id, item.sha256, item.size_bytes
    receipt = routes.DeliveryAcknowledgement(sha256=digest, size_bytes=size, durable_storage_confirmed=True)
    with pytest.raises(HTTPException):
        routes.acknowledge_delivery(env.tenant, env.integration, job_id, item_id, receipt, env.context)
    monkeypatch.setattr(routes, "StreamingResponse", lambda chunks, **kwargs: SimpleNamespace(body_iterator=chunks))
    response = routes.independent_download(env.tenant, env.integration, job_id, item_id, env.context)
    assert b"".join(response.body_iterator) == b"%PDF-test"
    with pytest.raises(HTTPException):
        routes.acknowledge_delivery(env.tenant, env.integration, job_id, item_id,
            receipt.model_copy(update={"sha256": "0" * 64}), env.context)
    assert routes.acknowledge_delivery(env.tenant, env.integration, job_id, item_id, receipt, env.context)["status"] == "verified"
    migration.migrate_once()
    with env.sessions() as db:
        assert db.get(StorageMigration, job_id).status == "completed"


def test_failed_copy_retries_without_deleting_source(storage_db, monkeypatch):
    env = storage_db
    start(env, "rubrica")
    original = migration.source_stream
    monkeypatch.setattr(migration, "source_stream", lambda *a: (_ for _ in ()).throw(RuntimeError("secret must not leak")))
    migration.migrate_once()
    with env.sessions() as db:
        item = db.scalar(select(MigrationItem))
        assert item.status == "retry" and item.error_code == "delivery_not_verified"
        assert item.attempts == 1
    monkeypatch.setattr(migration, "source_stream", original)
    migration.migrate_once()
    with env.sessions() as db:
        assert db.scalar(select(MigrationItem)).status == "verified"


def test_calculator_exact_proration_and_invalid_journal():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    end = start + timedelta(days=30)
    changes = [(start, 2_000_000_000), (start + timedelta(days=15), -1_000_000_000)]
    assert calculator.byte_time(1_000_000_000, changes, start, end) == Decimal(1_000_000_000 * 15 * 86400)
    assert calculator.byte_time(1_000_000_000, [], start, end) == 0
    assert calculator.byte_time(1_500_000_000, [], start, end) == Decimal(500_000_000 * 30 * 86400)
    with pytest.raises(HTTPException):
        calculator.byte_time(0, [(start, 1)], start, end)


def test_calculator_shares_allowance_per_tenant_and_cycle_cutoff(storage_db):
    env = storage_db
    start = datetime(2026, 11, 1, tzinfo=UTC)
    with env.sessions.begin() as db:
        db.add(BillingAccountEntity(tenant_id=env.tenant, status="active", current_product_code="rubrica_enterprise", usage_period_starts_at=start))
        db.add(EnterpriseQuota(tenant_id=env.tenant, sandbox=False, storage_bytes=2_000_000_000))
        db.add(EnterpriseQuota(tenant_id=env.tenant, sandbox=True, storage_bytes=1))
    with env.sessions() as db:
        result = calculator.calculate(db, env.tenant, False, now=start + timedelta(days=15))
        assert result["accrued_gb_month"] == "0.5" and result["accrued_amount_minor"] == 0
        assert result["included_bytes"] == 1_000_000_000
        next_cycle = calculator.calculate(db, env.tenant, False, now=start + timedelta(days=30))
        assert next_cycle["accrued_gb_month"] == "0"
        assert next_cycle["cycle_start"] == start + timedelta(days=30)
        assert calculator.calculate(db, env.tenant, True, now=start + timedelta(days=15))["current_bytes"] == 1


def test_destination_rejects_unexpected_configuration_and_invalid_bucket():
    with pytest.raises(ValidationError):
        destinations.DestinationCreate(name="Managed", kind="rubrica", configuration=configuration())
    with pytest.raises(ValidationError):
        destinations.S3Configuration(**(configuration() | {"bucket": "../escape"}))


def test_expired_request_is_migrated_automatically_on_next_poll(storage_db):
    env = storage_db
    with env.sessions.begin() as db:
        document = db.get(EnterpriseDocument, env.document)
        request = EnterpriseRequest(compartment_id=env.compartment, document_id=env.document, document_sha256=document.sha256,
            idempotency_key="request", payload_sha256="0" * 64, signers=[], status="open",
            expires_at=datetime.now(UTC) + timedelta(days=1), token_public_id="token")
        db.add(request)
        db.flush()
        request_id = request.id
    job_id = start(env, "rubrica")
    migration.migrate_once()
    with env.sessions.begin() as db:
        assert db.get(StorageMigration, job_id).status == "pending"
        db.get(EnterpriseRequest, request_id).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    migration.migrate_once()
    with env.sessions() as db:
        assert db.get(StorageMigration, job_id).status == "completed"


@pytest.mark.parametrize("status,expected", [("quarantined", "waiting_scan"), ("rejected", "blocked")])
def test_uncleared_documents_are_never_exported(storage_db, status, expected):
    env = storage_db
    with env.sessions.begin() as db:
        db.get(EnterpriseDocument, env.document).status = status
    start(env, "rubrica")
    migration.migrate_once()
    with env.sessions() as db:
        assert db.scalar(select(MigrationDocument)).status == expected
        assert db.scalar(select(MigrationItem)) is None


def test_future_policy_enrolls_only_its_integration_and_freezes_destination(storage_db):
    from core_api.modules.enterprise.storage_policy import enroll_document
    from core_api.modules.enterprise.machine_context import MachineContext
    env = storage_db
    destination = destinations.create_destination(env.tenant, destinations.DestinationCreate(name="NAS", kind="independent"), True, env.context)
    routes.start_migration(env.tenant, env.integration, routes.MigrationCreate(destination_id=destination["id"],
        acknowledge_plaintext_export=True, include_existing=False, apply_to_new_uploads=True), env.context)
    context = MachineContext(env.tenant, env.integration, env.compartment, "token", True)
    with env.sessions.begin() as db:
        enroll_document(db, context, env.document)
    with env.sessions() as db:
        entry = db.scalar(select(MigrationDocument))
        assert entry.document_id == env.document
        assert db.get(StorageMigration, entry.migration_id).destination_id == destination["id"]
    with env.sessions.begin() as db:
        enroll_document(db, MachineContext(uuid4(), uuid4(), uuid4(), "other", True), uuid4())
    with env.sessions() as db:
        assert len(list(db.scalars(select(MigrationDocument)))) == 1


def test_interrupted_independent_stream_cannot_acknowledge_delivery(storage_db, monkeypatch):
    env = storage_db
    job_id = start(env)
    migration.migrate_once()
    with env.sessions() as db:
        item = db.scalar(select(MigrationItem))
        item_id, digest, size = item.id, item.sha256, item.size_bytes
    monkeypatch.setattr(routes, "StreamingResponse", lambda chunks, **kwargs: SimpleNamespace(body_iterator=chunks))
    response = routes.independent_download(env.tenant, env.integration, job_id, item_id, env.context)
    next(response.body_iterator)
    response.body_iterator.close()
    with env.sessions() as db:
        assert db.get(MigrationItem, item_id).downloaded_at is None
    with pytest.raises(HTTPException):
        routes.acknowledge_delivery(env.tenant, env.integration, job_id, item_id,
            routes.DeliveryAcknowledgement(sha256=digest, size_bytes=size, durable_storage_confirmed=True), env.context)


def test_wrong_migration_cannot_download_another_jobs_item(storage_db):
    env = storage_db
    start(env)
    migration.migrate_once()
    with env.sessions() as db:
        item = db.scalar(select(MigrationItem))
    with pytest.raises(HTTPException) as error:
        routes.independent_download(env.tenant, env.integration, uuid4(), item.id, env.context)
    assert error.value.status_code == 404


def test_s3_write_is_not_success_until_destination_hash_is_verified(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request.method)
        if request.method == "PUT":
            return httpx.Response(200)
        return httpx.Response(404) if len(calls) == 1 else httpx.Response(200, stream=httpx.ByteStream(b"bad"))
    client_mock(monkeypatch, handler)
    with pytest.raises(HTTPException):
        s3.S3Destination(configuration()).ensure_object("file", sha256(b"pdf").hexdigest(), 3, "application/pdf", lambda: BytesIO(b"pdf"))
    assert calls == ["GET", "PUT", "GET"]


def test_s3_existing_divergent_file_is_never_overwritten(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, stream=httpx.ByteStream(b"bad"))
    client_mock(monkeypatch, handler)
    with pytest.raises(HTTPException):
        s3.S3Destination(configuration()).ensure_object("file", sha256(b"pdf").hexdigest(), 3, "application/pdf", lambda: BytesIO(b"pdf"))
    assert calls == ["GET"]


def test_storage_schema_upgrade_downgrade_preserves_originals():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa
    path = Path(__file__).parents[1] / "apps/core_api/alembic/versions/0037_enterprise_storage.py"
    spec = importlib.util.spec_from_file_location("storage_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        for table in ("enterprise_documents", "enterprise_signatures"):
            db.execute(sa.text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, storage_key TEXT NOT NULL)"))
            db.execute(sa.text(f"INSERT INTO {table} VALUES ('existing', 'original-key')"))
        with Operations.context(MigrationContext.configure(db)):
            module.upgrade()
            assert "enterprise_storage_migrations" in sa.inspect(db).get_table_names()
            for table in ("enterprise_documents", "enterprise_signatures"):
                assert db.execute(sa.text(f"SELECT storage_key, rubrica_copy_deleted_at FROM {table}")).one() == ("original-key", None)
            module.downgrade()
        for table in ("enterprise_documents", "enterprise_signatures"):
            assert db.scalar(sa.text(f"SELECT storage_key FROM {table}")) == "original-key"


def test_slow_storage_stream_is_bounded_by_total_transfer_time(monkeypatch):
    client_mock(monkeypatch, lambda _: httpx.Response(200, stream=httpx.ByteStream(b"pdf")))
    clock = iter([0, 61])
    monkeypatch.setattr(s3, "monotonic", lambda: next(clock))
    with pytest.raises(HTTPException) as error:
        s3.S3Destination(configuration()).read_verified("file", sha256(b"pdf").hexdigest(), 3)
    assert error.value.status_code == 504


def test_manifest_includes_every_signed_artifact_and_its_evidence(storage_db):
    import json
    from core_api.modules.enterprise.entities import EnterpriseSignature
    env = storage_db
    with env.sessions.begin() as db:
        document = db.get(EnterpriseDocument, env.document)
        request = EnterpriseRequest(compartment_id=env.compartment, document_id=env.document, document_sha256=document.sha256,
            idempotency_key="request", payload_sha256="0" * 64, signers=[], status="completed",
            expires_at=datetime.now(UTC) + timedelta(days=1), token_public_id="token")
        db.add(request)
        db.flush()
        for index in range(2):
            content = f"%PDF-signed-{index}".encode()
            digest = sha256(content).hexdigest()
            key, size = env.store.put(BytesIO(content), filename="signed.pdf", sha256=digest, scope="tenant")
            evidence = {"signer": str(uuid4())}
            db.add(EnterpriseSignature(request_id=request.id, signer_id=uuid4(), signed_at=datetime.now(UTC),
                artifact_storage_key=key, artifact_sha256=digest, artifact_size=size, evidence=evidence,
                evidence_sha256=sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), evidence_hmac="a" * 64))
    job_id = start(env, "rubrica")
    migration.migrate_once()
    with env.sessions() as db:
        assert db.get(StorageMigration, job_id).status == "completed"
        items = list(db.scalars(select(MigrationItem)))
        assert len(items) == 5
        assert sorted(item.source_kind for item in items) == ["artifact", "artifact", "evidence", "evidence", "original"]
        assert all(item.status == "verified" for item in items)


def test_bad_manifest_does_not_starve_other_documents(storage_db, monkeypatch):
    env = storage_db
    with env.sessions.begin() as db:
        key, size = env.store.put(BytesIO(b"%PDF-second"), filename="second.pdf", sha256=sha256(b"%PDF-second").hexdigest(), scope="tenant")
        db.add(EnterpriseDocument(compartment_id=env.compartment, filename="second.pdf", storage_key=key,
            sha256=sha256(b"%PDF-second").hexdigest(), size_bytes=size, status="ready", token_public_id="token", idempotency_key="second"))
    start(env, "rubrica")
    original = migration.manifest
    def manifest(db, document):
        if document.id == env.document:
            raise HTTPException(409, "mismatch")
        return original(db, document)
    monkeypatch.setattr(migration, "manifest", manifest)
    assert migration.migrate_once()
    with env.sessions() as db:
        assert sorted(entry.status for entry in db.scalars(select(MigrationDocument))) == ["manifest_invalid", "verified"]


def test_storage_byte_time_is_reconstructed_from_real_ledger_changes(storage_db):
    from core_api.modules.enterprise.machine_context import MachineContext
    from core_api.modules.enterprise.usage import record_usage
    env = storage_db
    start = datetime(2026, 11, 1, tzinfo=UTC)
    context = MachineContext(env.tenant, env.integration, env.compartment, "token", False)
    with env.sessions.begin() as db:
        db.add(BillingAccountEntity(tenant_id=env.tenant, status="active", current_product_code="rubrica_enterprise", usage_period_starts_at=start))
        db.add(EnterpriseQuota(tenant_id=env.tenant, sandbox=False, storage_bytes=1_000_000_000))
        record_usage(db, context, "document.uploaded", uuid4(), bytes_count=1_000_000_000, now=start)
        record_usage(db, context, "signature.completed", uuid4(), bytes_count=1_000_000_000, now=start)
        record_usage(db, context, "storage.removed", uuid4(), bytes_count=1_000_000_000, now=start + timedelta(days=15))
        record_usage(db, context, "download.completed", uuid4(), bytes_count=1_000_000_000, now=start + timedelta(days=15))
    with env.sessions() as db:
        result = calculator.calculate(db, env.tenant, False, now=start + timedelta(days=29))
        assert result["accrued_gb_month"] == "0.5"
        assert result["current_bytes"] == 1_000_000_000
