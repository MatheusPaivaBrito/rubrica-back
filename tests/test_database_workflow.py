import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from pypdf import PdfReader, PdfWriter

from auth_api.infrastructure.database.connection import SessionLocal as AuthSessionLocal
from auth_api.infrastructure.settings import settings as auth_settings
from auth_api.main import app as auth_app
from auth_api.modules.accounts import account_service, tenant_client
from auth_api.modules.sessions.session_service import session_service
from auth_api.modules.users.user_entity import UserEntity
from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings as core_settings
from core_api.main import app as core_app
from core_api.modules.billing.billing_entity import BillingAccountEntity, BillingEventEntity
from core_api.modules.billing.billing_service import billing_service
from core_api.modules.billing.notification_client import BillingEmailDeliveryError
from core_api.modules.billing.providers.fake_provider import FakeBillingProvider
from core_api.modules.document.document_entity import DocumentEntity
from core_api.modules.document.document_schema import DocumentCreate
from core_api.modules.document.storage import LocalDocumentStorage
from core_api.modules.signature_request.database_workflow_service import DatabaseSignatureWorkflowService
from core_api.modules.signature_request.signature_request_entity import (
    SignatureEntity,
    SignatureOperationEntity,
    SignatureRequestEntity,
)
from core_api.modules.signature_request import identity_client
from core_api.modules.signature_request.workflow_schema import ReopenSignatureRequest, RequestStatus, SignatureMode, SignatureRequestCreate, SignerCreate, StampPosition
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.signature_request.workflow_service import WorkflowError
from shared_kernel.time.datetime_service import DateTimeService
from toolbox.seeds.local_test_accounts import _ensure_test_cpf


pytestmark = pytest.mark.skipif(os.getenv("RUBRICA_DATABASE_TESTS") != "1", reason="requires Rubrica PostgreSQL")


@pytest.fixture(scope="module", autouse=True)
def isolated_core_database() -> None:
    """Keep integration records isolated without bypassing append-only triggers."""
    with SessionLocal.begin() as db:
        db.execute(text("TRUNCATE TABLE tenants CASCADE"))
    yield
    with SessionLocal.begin() as db:
        db.execute(text("TRUNCATE TABLE tenants CASCADE"))


@pytest.fixture
def auth_identities(monkeypatch: pytest.MonkeyPatch):
    users = []
    emails = ("database@example.com", "second@example.com", "signed@example.com", "pending@example.com")
    with AuthSessionLocal.begin() as db:
        for index, email in enumerate(emails, start=1000):
            user = UserEntity(email=email, email_verified=True, password_hash="unused")
            db.add(user)
            db.flush()
            _ensure_test_cpf(db, user, index)
            users.append(user.id)

    service_key = "qa-core-to-auth"
    monkeypatch.setattr(auth_settings, "CORE_INTERNAL_SERVICE_KEY", service_key)
    monkeypatch.setattr(core_settings, "CORE_INTERNAL_SERVICE_KEY", service_key)
    try:
        with TestClient(auth_app) as client:
            def get_identity(url, *, params, headers, timeout):
                return client.get(url, params=params, headers=headers)

            monkeypatch.setattr(
                identity_client, "httpx",
                SimpleNamespace(get=get_identity, HTTPError=identity_client.httpx.HTTPError),
            )
            yield
    finally:
        with AuthSessionLocal.begin() as db:
            db.execute(delete(UserEntity).where(UserEntity.id.in_(users)))


@pytest.fixture
def trusted_timestamp(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"count": 0, "failures_remaining": 0}

    def apply_timestamp(pdf: bytes) -> tuple[bytes, dict[str, object]]:
        calls["count"] += 1
        # The external provider callback must run after the preparation
        # transaction released its request lock.
        with SessionLocal.begin() as db:
            operation = db.scalar(
                select(SignatureOperationEntity).where(
                    SignatureOperationEntity.status == "processing"
                )
            )
            assert operation is not None
            locked_request = db.scalar(
                select(SignatureRequestEntity)
                .where(SignatureRequestEntity.id == operation.signature_request_id)
                .with_for_update(nowait=True)
            )
            assert locked_request is not None
        if calls["failures_remaining"]:
            calls["failures_remaining"] -= 1
            raise RuntimeError("simulated timestamp outage")
        return pdf, {
            "provider": "integration-test",
            "token_sha256": "0" * 64,
            "policy_oid": "2.16.76.1.2",
        }

    monkeypatch.setattr(
        "core_api.modules.signature_request.serpro_timestamp_service.apply_serpro_timestamp",
        apply_timestamp,
    )
    return calls


@pytest.mark.skipif(not os.getenv("RUBRICA_TEST_REDIS_URL"), reason="requires isolated Redis")
def test_registration_provisions_one_workspace_and_rejects_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    unique = uuid4().hex
    email = f"registration-{unique}@example.test"
    payload = {
        "name": "Test registration",
        "email": email,
        "country_code": "BR",
        "identity_document_type": "PASSPORT",
        "identity_document_country": "JP",
        "identity_document_value": unique[:12],
    }
    sent = []
    service_key = "qa-auth-to-core"
    monkeypatch.setattr(auth_settings, "CORE_INTERNAL_SERVICE_KEY", service_key)
    monkeypatch.setattr(core_settings, "CORE_INTERNAL_SERVICE_KEY", service_key)
    monkeypatch.setattr(
        account_service, "request_account_email", lambda **message: sent.append(message)
    )
    with (
        Redis.from_url(os.environ["RUBRICA_TEST_REDIS_URL"], decode_responses=True) as redis,
        TestClient(auth_app) as auth,
        TestClient(core_app) as core,
    ):
        monkeypatch.setattr(session_service, "_redis", redis)

        def provision(url, *, json, headers, timeout):
            return core.post(url, json=json, headers=headers)

        monkeypatch.setattr(
            tenant_client, "httpx",
            SimpleNamespace(post=provision, HTTPError=tenant_client.httpx.HTTPError),
        )
        try:
            for missing in ("country_code", "identity_document_value"):
                invalid = {key: value for key, value in payload.items() if key != missing}
                assert auth.post("/auth/register", json=invalid).status_code == 422
            assert auth.post("/auth/register", json=payload).status_code == 202
            for duplicate in (
                payload | {"email": email.upper(), "identity_document_value": unique[-12:]},
                payload | {"email": f"duplicate-{email}"},
            ):
                conflict = auth.post("/auth/register", json=duplicate)
                assert conflict.status_code == 409
                assert conflict.json() == {"detail": "E-mail or identity document is already registered"}
            assert len(sent) == 1
            assert sent[0]["recipient"] == email
            credentials = {"email": email, "password": "Qa-Example-Password-123!"}
            assert auth.post("/auth/login", json=credentials).status_code == 401
            activation_link = next(
                line for line in sent[0]["email"].text.splitlines() if "/verify-email?" in line
            )
            token = parse_qs(urlsplit(activation_link).query)["token"][0]
            activation = {"token": token, "new_password": credentials["password"]}
            assert auth.post("/auth/verify-email", json=activation).status_code == 200
            assert auth.post("/auth/verify-email", json=activation).status_code == 422
            login = auth.post("/auth/login", json=credentials)
            assert login.status_code == 200
            assert login.json()["access_token"]

            with AuthSessionLocal() as db:
                user = db.scalar(select(UserEntity).where(UserEntity.email == email))
                assert user is not None and user.is_active and user.email_verified
                user_id = user.id
                assert db.scalar(select(UserEntity.id).where(UserEntity.email == f"duplicate-{email}")) is None
            with SessionLocal() as db:
                workspace, = db.scalars(
                    select(TenantEntity)
                    .join(TenantMemberEntity, TenantMemberEntity.tenant_id == TenantEntity.id)
                    .where(TenantMemberEntity.auth_user_uuid == user_id)
                )
                assert (workspace.kind, workspace.country_code, workspace.currency) == ("personal", "BR", "BRL")
        finally:
            with AuthSessionLocal.begin() as db:
                db.execute(delete(UserEntity).where(UserEntity.email.in_((email, f"duplicate-{email}"))))


def test_signature_entitlement_limit_and_active_subscription() -> None:
    tenant_id = uuid4()
    with SessionLocal.begin() as db:
        db.add(TenantEntity(id=tenant_id, name="Entitlement test", slug=f"entitlement-{tenant_id}"))
        db.flush()
        db.add(
            BillingAccountEntity(
                tenant_id=tenant_id,
                status="not_configured",
                signatures_used=4,
                free_signatures_limit=5,
            )
        )

    try:
        with SessionLocal.begin() as db:
            billing_service.consume_signature(db, tenant_id)

        with pytest.raises(WorkflowError) as error:
            with SessionLocal.begin() as db:
                billing_service.consume_signature(db, tenant_id)
        assert error.value.status_code == 402

        with SessionLocal.begin() as db:
            account = db.scalar(
                select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id)
            )
            assert account is not None
            assert account.signatures_used == 5
            account.status = "active"

        with SessionLocal.begin() as db:
            billing_service.consume_signature(db, tenant_id)

        with SessionLocal() as db:
            account = db.scalar(
                select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id)
            )
            assert account is not None
            assert account.signatures_used == 5
    finally:
        pass


@pytest.fixture
def subscription_webhook(monkeypatch):
    tenant_id = uuid4()
    with SessionLocal.begin() as db:
        db.add(TenantEntity(id=tenant_id, name="Webhook QA", slug=f"webhook-{tenant_id}"))
        db.flush()
        db.add(BillingAccountEntity(tenant_id=tenant_id, signatures_used=3))
    monkeypatch.setattr(billing_service, "_get_provider", FakeBillingProvider)
    event_id = f"evt_qa_{uuid4().hex}"
    now = int(DateTimeService.utc_now().timestamp())
    payload = json.dumps({
        "id": event_id,
        "type": "customer.subscription.created",
        "created": now,
        "data": {"object": {
            "id": f"sub_{tenant_id.hex}",
            "status": "active",
            "current_period_start": now,
            "current_period_end": now + 30 * 24 * 3600,
            "metadata": {"tenant_id": str(tenant_id), "product_code": "rubrica_base"},
        }},
    }).encode()
    return tenant_id, event_id, payload


def test_webhook_retry_success_is_preserved_when_an_earlier_attempt_records_failure(
    monkeypatch, subscription_webhook,
):
    tenant_id, event_id, payload = subscription_webhook
    rolled_back = Event()
    retry_finished = Event()
    original_begin = SessionLocal.begin
    apply_event = billing_service._apply_event
    should_fail = True

    class TransientFailure(RuntimeError):
        pass

    def apply_then_fail_once(*args):
        nonlocal should_fail
        result = apply_event(*args)
        if should_fail:
            should_fail = False
            raise TransientFailure("First delivery rolled back")
        return result

    @contextmanager
    def pause_after_rollback():
        try:
            with original_begin() as db:
                yield db
        except TransientFailure:
            rolled_back.set()
            assert retry_finished.wait(10), "Parallel retry did not finish"
            raise

    monkeypatch.setattr(billing_service, "_apply_event", apply_then_fail_once)
    monkeypatch.setattr(SessionLocal, "begin", pause_after_rollback)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(billing_service.receive_webhook, payload, "qa")
        try:
            assert rolled_back.wait(10), "First delivery did not reach rollback"
            assert not billing_service.receive_webhook(payload, "qa").duplicate
        finally:
            retry_finished.set()
        with pytest.raises(TransientFailure):
            first.result(timeout=10)

    with SessionLocal() as db:
        event = db.scalars(select(BillingEventEntity).filter_by(provider_event_id=event_id)).one()
        account = db.scalars(select(BillingAccountEntity).filter_by(tenant_id=tenant_id)).one()
        assert (event.status, event.error_code) == ("processed", None)
        assert (account.status, account.signatures_used) == ("active", 3)
    assert billing_service.receive_webhook(payload, "qa").duplicate


def test_webhook_email_outage_does_not_roll_back_subscription_or_reapply_it(
    monkeypatch, subscription_webhook,
):
    tenant_id, event_id, payload = subscription_webhook
    notifications = []

    def unavailable(_db, delivered_event_id, *_args):
        notifications.append(delivered_event_id)
        raise BillingEmailDeliveryError("Simulated local email outage")

    monkeypatch.setattr(billing_service, "_notify_billing_event", unavailable)
    assert not billing_service.receive_webhook(payload, "qa").duplicate
    assert billing_service.receive_webhook(payload, "qa").duplicate
    assert notifications == [event_id]
    with SessionLocal() as db:
        assert db.scalar(select(BillingAccountEntity.status).filter_by(tenant_id=tenant_id)) == "active"
        assert db.scalar(select(BillingEventEntity.status).filter_by(provider_event_id=event_id)) == "processed"


def test_webhook_persistence_error_is_not_reported_as_duplicate(subscription_webhook):
    _, event_id, payload = subscription_webhook
    event = json.loads(payload)
    event["data"]["object"]["metadata"]["tenant_id"] = str(uuid4())

    with pytest.raises(IntegrityError):
        billing_service.receive_webhook(json.dumps(event).encode(), "qa")
    with SessionLocal() as db:
        assert db.scalar(select(BillingEventEntity.id).filter_by(provider_event_id=event_id)) is None


def test_webhook_insert_collision_resumes_the_unprocessed_event(monkeypatch, subscription_webhook):
    tenant_id, event_id, payload = subscription_webhook
    original_begin = SessionLocal.begin
    first_insert = True

    @contextmanager
    def insert_from_competing_delivery():
        nonlocal first_insert
        if first_insert:
            first_insert = False
            with original_begin() as db:
                db.add(BillingEventEntity(
                    tenant_id=tenant_id,
                    provider="stripe",
                    provider_event_id=event_id,
                    event_type="customer.subscription.created",
                    resource_id=f"sub_{tenant_id.hex}",
                    payload_hash=sha256(payload).hexdigest(),
                    status="received",
                ))
        with original_begin() as db:
            yield db

    monkeypatch.setattr(SessionLocal, "begin", insert_from_competing_delivery)
    assert not billing_service.receive_webhook(payload, "qa").duplicate
    assert billing_service.receive_webhook(payload, "qa").duplicate
    with SessionLocal() as db:
        assert db.scalar(select(BillingEventEntity.status).filter_by(provider_event_id=event_id)) == "processed"


@pytest.mark.usefixtures("auth_identities")
def test_database_workflow_round_trip(
    tmp_path: Path, trusted_timestamp: dict[str, int]
) -> None:
    service = DatabaseSignatureWorkflowService(LocalDocumentStorage(tmp_path / "objects"))
    organization = f"database-smoke-{uuid4()}"
    try:
        with SessionLocal.begin() as db:
            tenant = TenantEntity(name="Database smoke test", slug=organization)
            db.add(tenant)
            db.flush()
            db.add(
                TenantMemberEntity(
                    tenant_id=tenant.id,
                    auth_user_id="operator",
                    role="admin",
                )
            )
            db.add(
                BillingAccountEntity(
                    tenant_id=tenant.id,
                    status="active",
                    current_product_code="rubrica_base",
                )
            )
        source = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.write(source)
        original = source.getvalue()
        document = service.create_document(DocumentCreate(organization_id=organization, title="Smoke", original_filename="smoke.pdf", content_type="application/pdf", created_by="operator"), original)
        with SessionLocal.begin() as db:
            foreign_tenant = TenantEntity(
                name="Foreign tenant",
                slug=f"foreign-{uuid4()}",
            )
            db.add(foreign_tenant)
            db.flush()
            db.add(
                TenantMemberEntity(
                    tenant_id=foreign_tenant.id,
                    auth_user_id="foreign-user@example.com",
                    role="admin",
                    status="active",
                )
            )
        with pytest.raises(WorkflowError) as cross_tenant_error:
            service.get_content(
                document.id,
                actor_id="foreign-user@example.com",
            )
        assert cross_tenant_error.value.status_code == 403
        request = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
        first_signer = service.add_signer(request.id, SignerCreate(name="Database User", email="database@example.com"), "operator")
        second_signer = service.add_signer(request.id, SignerCreate(name="Second User", email="second@example.com"), "operator")
        for signer in (first_signer, second_signer):
            service.update_signer_signature_mode(request.id, signer.id, "operator", SignatureMode.SERPRO_TIMESTAMP)
        service.open_request(request.id, "operator")
        link = service.create_signing_link(request.id, "operator")
        token = link.signing_url.rsplit("/", maxsplit=1)[-1]
        stamp = StampPosition(page=1, x=0.65, y=0.8)
        trusted_timestamp["failures_remaining"] = 1
        with pytest.raises(RuntimeError, match="simulated timestamp outage"):
            service.sign(token, "database@example.com", True, stamp)
        with SessionLocal() as db:
            failed_operation = db.scalar(
                select(SignatureOperationEntity).where(
                    SignatureOperationEntity.signature_request_id == request.id
                )
            )
            assert failed_operation is not None
            assert failed_operation.status == "failed"
            assert failed_operation.attempt_count == 1
            tenant_id = db.scalar(
                select(DocumentEntity.tenant_id).where(DocumentEntity.id == document.id)
            )
            billing_account = db.scalar(
                select(BillingAccountEntity).where(
                    BillingAccountEntity.tenant_id == tenant_id
                )
            )
            assert billing_account is not None
            assert billing_account.signatures_used == 0
        service.sign(token, "database@example.com", True, stamp)
        service.sign(token, "database@example.com", True, stamp)
        assert trusted_timestamp["count"] == 2
        assert service.get_request(request.id, "operator").status == RequestStatus.OPEN
        assert service.signing_signed_document(token, "second@example.com")[2].startswith(b"%PDF")
        service.sign(token, "second@example.com", True, StampPosition(page=1, x=0.35, y=0.7))
        assert trusted_timestamp["count"] == 3
        consolidated = service.signing_signed_document(token, "second@example.com")[2]
        consolidated_text = "\n".join((page.extract_text() or "") for page in PdfReader(BytesIO(consolidated)).pages)
        assert "Database User" in consolidated_text
        assert "Second User" in consolidated_text
        with SessionLocal() as db:
            signatures = list(db.scalars(
                select(SignatureEntity)
                .where(SignatureEntity.signature_request_id == request.id)
                .order_by(SignatureEntity.signed_at, SignatureEntity.id)
            ).all())
            assert signatures[1].document_sha256 == signatures[0].artifact_sha256

        completed_request = service.get_request(request.id, "operator")
        assert completed_request.status == RequestStatus.COMPLETED
        assert completed_request.document_title == "Smoke"
        assert completed_request.original_filename == "smoke.pdf"
        listed_document = next(
            item for item in service.list_documents("operator") if item.id == document.id
        )
        assert listed_document.size_bytes == len(original)
        assert listed_document.signature_request_count == 1
        assert listed_document.completed_signature_count == 2
        assert service.get_content(document.id)[1] == original
        with SessionLocal.begin() as db:
            persisted_request = db.scalar(select(SignatureRequestEntity).where(SignatureRequestEntity.id == request.id))
            persisted_request.expires_at = DateTimeService.utc_now() - timedelta(days=730)
        assert service.signing_context(token, "database@example.com").stamp == stamp.model_copy(
            update={"country_code": "BR", "template": "BR", "show_flag": True, "locale": "pt-BR"}
        )
        assert service.signing_signed_document(token, "database@example.com")[2].startswith(b"%PDF")
        assert service.get_signing_link(request.id, "operator").signing_url == link.signing_url
        historical_link = service.create_signing_link(request.id, "operator")
        historical_token = historical_link.signing_url.rsplit("/", maxsplit=1)[-1]
        assert service.signing_signed_document(historical_token, "database@example.com")[2].startswith(b"%PDF")
        with pytest.raises(WorkflowError) as denied:
            service.signing_context(historical_token, "outside-admin@example.com", administrator=True)
        assert denied.value.status_code == 403
        with pytest.raises(WorkflowError) as denied:
            service.signing_document(historical_token, "outside-admin@example.com", administrator=True)
        assert denied.value.status_code == 403
        with pytest.raises(WorkflowError) as denied:
            service.signing_signed_document(historical_token, "outside-admin@example.com", administrator=True)
        assert denied.value.status_code == 403
        with SessionLocal() as db:
            owner_tenant_id = db.scalar(select(DocumentEntity.tenant_id).where(DocumentEntity.id == document.id))
        contacts = service.list_signer_contacts(owner_tenant_id, "operator")
        assert [(contact.name, contact.email) for contact in contacts] == [("Second User", "second@example.com"), ("Database User", "database@example.com")]
        assert [contact.email for contact in service.list_signer_contacts(owner_tenant_id, "operator", "database")] == ["database@example.com"]
        with pytest.raises(WorkflowError) as denied:
            service.list_signer_contacts(owner_tenant_id, "outside-admin@example.com")
        assert denied.value.status_code == 403
        administrator_view = service.signing_context(historical_token, "operator", administrator=True)
        assert administrator_view.viewer_mode == "administrator"
        assert administrator_view.request.status == RequestStatus.COMPLETED
        assert service.signing_signed_document(historical_token, "operator", administrator=True)[2].startswith(b"%PDF")
        signer_view = service.signing_context(historical_token, "database@example.com", administrator=True)
        assert signer_view.viewer_mode == "signer"
        filename, artifact_hash, artifact = service.signed_document(request.id)
        assert filename.endswith("signed.pdf")
        assert artifact_hash
        assert artifact.startswith(b"%PDF")
        artifact_metadata = PdfReader(BytesIO(artifact)).metadata
        assert artifact_metadata.get("/RubricaEvidenceJSON")
        evidence = service.signature_evidence(request.id, "operator")
        assert len(evidence) == 2
        assert evidence[0].evidence_sha256
        assert evidence[0].subject_hmac_sha256 != "database@example.com"
        assert "signature.completed" in [event.action for event in service.audit_events(request.id, "operator")]
        with pytest.raises(IntegrityError):
            with SessionLocal.begin() as db:
                signature_id = db.scalar(
                    select(SignatureEntity.id).where(
                        SignatureEntity.signature_request_id == request.id
                    ).limit(1)
                )
                db.execute(
                    update(SignatureEntity)
                    .where(SignatureEntity.id == signature_id)
                    .values(document_sha256="f" * 64)
                )
        with SessionLocal() as db:
            tenant_id = db.scalar(
                select(DocumentEntity.tenant_id).where(DocumentEntity.id == document.id)
            )
            billing_account = db.scalar(
                select(BillingAccountEntity).where(
                    BillingAccountEntity.tenant_id == tenant_id
                )
            )
            assert billing_account is not None
            assert billing_account.signatures_used == 0
            assert billing_account.free_signatures_limit == 5
    finally:
        pass


@pytest.mark.usefixtures("auth_identities")
def test_expired_request_reopens_as_immutable_round_with_signed_base(tmp_path: Path) -> None:
    service = DatabaseSignatureWorkflowService(LocalDocumentStorage(tmp_path / "round-objects"))
    organization = f"reopen-{uuid4()}"
    with SessionLocal.begin() as db:
        tenant = TenantEntity(name="Reopening test", slug=organization)
        db.add(tenant)
        db.flush()
        db.add(TenantMemberEntity(tenant_id=tenant.id, auth_user_id="operator", role="admin"))
        db.add(BillingAccountEntity(tenant_id=tenant.id, status="active", current_product_code="rubrica_base"))
    source = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(source)
    document = service.create_document(DocumentCreate(organization_id=organization, title="Round test", original_filename="round.pdf", content_type="application/pdf", created_by="operator"), source.getvalue())
    first = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
    service.add_signer(first.id, SignerCreate(name="Signed User", email="signed@example.com"), "operator")
    pending = service.add_signer(first.id, SignerCreate(name="Pending User", email="pending@example.com"), "operator")
    service.open_request(first.id, "operator")
    token = service.create_signing_link(first.id, "operator").signing_url.rsplit("/", 1)[-1]
    service.sign(token, "signed@example.com", True, StampPosition(page=1, x=0.5, y=0.5))
    signed_bytes = service.signed_document(first.id, "operator")[2]
    with SessionLocal.begin() as db:
        persisted = db.get(SignatureRequestEntity, first.id)
        assert persisted is not None
        persisted.expires_at = DateTimeService.utc_now() - timedelta(minutes=1)

    assert service.get_request(first.id, "operator").status == RequestStatus.EXPIRED
    with pytest.raises(WorkflowError) as expired_link:
        service.create_signing_link(first.id, "operator")
    assert expired_link.value.status_code == 409
    payload = ReopenSignatureRequest(
        expires_at=DateTimeService.utc_now() + timedelta(days=2),
        reason="Prazo solicitado pelo emissor",
        pending_signer_ids=[pending.id],
    )
    reopened = service.reopen_request(first.id, "operator", payload)
    duplicate = service.reopen_request(first.id, "operator", payload)

    assert duplicate.id == reopened.id
    assert reopened.parent_request_id == first.id
    assert reopened.round_number == 2
    assert reopened.preserved_signature_count == 1
    assert reopened.status == RequestStatus.DRAFT
    assert [item.email for item in service.list_signers(reopened.id, "operator")] == ["pending@example.com"]
    with SessionLocal() as db:
        unchanged = db.get(SignatureRequestEntity, first.id)
        child = db.get(SignatureRequestEntity, reopened.id)
        assert unchanged is not None and unchanged.status == RequestStatus.OPEN.value
        assert child is not None and child.base_artifact_sha256 == sha256(signed_bytes).hexdigest()

    service.open_request(reopened.id, "operator")
    reopened_token = service.create_signing_link(reopened.id, "operator").signing_url.rsplit("/", 1)[-1]
    metadata, presented = service.signing_document(reopened_token, "pending@example.com")
    assert presented == signed_bytes
    assert metadata.sha256 == sha256(signed_bytes).hexdigest()
    service.sign(reopened_token, "pending@example.com", True, StampPosition(page=1, x=0.3, y=0.7))
    final = service.signed_document(reopened.id, "operator")[2]
    evidence = PdfReader(BytesIO(final)).metadata["/RubricaEvidenceJSON"]
    assert evidence.count('"schema":"rubrica-signature-evidence-v1"') == 2
