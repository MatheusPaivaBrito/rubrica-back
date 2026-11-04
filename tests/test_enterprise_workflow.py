from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from fastapi import HTTPException, Response
from pypdf import PdfWriter
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import core_api.infrastructure.database.loader  # noqa: F401
from core_api.infrastructure.database.connection import Base
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.document.storage import LocalDocumentStorage
from core_api.modules.enterprise import document_access, document_router, request_router, scanning, signing_service
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseDocument, EnterpriseIntegration, EnterpriseSignature
from core_api.modules.enterprise.machine_context import MachineContext
from core_api.modules.enterprise.request_router import RequestInput, SessionInput
from core_api.modules.enterprise.signing_router import ConsentCommand
from core_api.modules.tenant.tenant_entity import TenantEntity


@pytest.fixture
def workflow(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    storage = LocalDocumentStorage(tmp_path)
    for module in (document_access, document_router, request_router, scanning, signing_service):
        monkeypatch.setattr(module, "SessionLocal", sessions)
        if hasattr(module, "configured_document_storage"):
            monkeypatch.setattr(module, "configured_document_storage", lambda _: storage)
    monkeypatch.setattr(signing_service.settings, "ENVIRONMENT", "development")
    tenant_id, integration_id, compartment_id = uuid4(), uuid4(), uuid4()
    with sessions.begin() as db:
        db.add(TenantEntity(id=tenant_id, name="Business", slug="business"))
        db.add(BillingAccountEntity(tenant_id=tenant_id, status="active", current_product_code="rubrica_enterprise"))
        db.add(EnterpriseIntegration(id=integration_id, tenant_id=tenant_id, name="ERP", environment="development", sandbox=True, created_by="admin"))
        db.add(EnterpriseCompartment(id=compartment_id, integration_id=integration_id, name="Customer"))
    context = MachineContext(tenant_id, integration_id, compartment_id, "public-token", True)
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.write(output)
    document = document_router.persist_upload(context, output.getvalue(), "test.pdf", "application/pdf", "upload-1")
    return context, document, sessions, storage


def payload(document, mode="evidence"):
    return RequestInput(document_id=document["id"], expires_at=datetime.now(UTC) + timedelta(days=1),
        signers=[{"external_id": "customer-person-1", "name": "Signer", "email": "signer@example.com",
                  "signature_mode": mode, "stamp": {"page": 1, "x": .5, "y": .8, "locale": "pt-BR"}}])


def test_evidence_workflow_is_scoped_frozen_and_idempotent(workflow, monkeypatch):
    context, document, sessions, storage = workflow
    data = payload(document)
    created = request_router.create_request(context, data, "request-1")
    assert request_router.create_request(context, data, "request-1")["id"] == created["id"]
    with pytest.raises(HTTPException) as error:
        request_router.open_request(created["id"], context)
    assert error.value.status_code == 409  # quarantine cannot be bypassed
    monkeypatch.setattr(scanning, "scan_stream", lambda _: "ready")
    assert scanning.scan_document(context, document["id"])["status"] == "ready"
    opened = request_router.open_request(created["id"], context)
    assert opened["status"] == "open"
    session = request_router.create_session(created["id"], SessionInput(signer_id=created["signers"][0]["id"]), Response(), context)
    command = ConsentCommand(consent=True, consent_version="rubrica-enterprise-evidence-v1", document_sha256=opened["document_sha256"])
    signed = signing_service.sign_evidence(session["session_token"], True, command,
                                         ip_address="127.0.0.1", user_agent="test")
    assert signed["simulated"] is True
    assert request_router.get_request(created["id"], context)["status"] == "completed"
    assert signing_service.sign_evidence(session["session_token"], True, command,
        ip_address="127.0.0.1", user_agent="test")["signature_id"] == signed["signature_id"]
    with sessions() as db:
        records = db.scalars(select(EnterpriseSignature)).all()
        assert len(records) == 1
        assert records[0].evidence["identity_source"] == "integrator_declared"
        assert "storage_key" not in document_access.metadata(db.get(EnterpriseDocument, document["id"]))
        with storage.get(records[0].artifact_storage_key) as stream:
            assert sha256(stream.read()).hexdigest() == signed["artifact_sha256"]
        with pytest.raises(HTTPException) as error:
            document_access.lookup_document(db, replace(context, compartment_id=uuid4()), document["id"])
        assert error.value.status_code == 404
        with pytest.raises(HTTPException):
            signing_service.resolve_session(db, session["session_token"], False)


def test_provider_modes_fail_closed_and_session_replacement(workflow, monkeypatch):
    context, document, sessions, _ = workflow
    monkeypatch.setattr(scanning, "scan_stream", lambda _: "ready")
    scanning.scan_document(context, document["id"])
    provider_request = request_router.create_request(context, payload(document, "serproid"), "provider-request")
    with pytest.raises(HTTPException) as error:
        request_router.open_request(provider_request["id"], replace(context, sandbox=False))
    assert error.value.status_code == 409
    created = request_router.create_request(context, payload(document), "evidence-request")
    request_router.open_request(created["id"], context)
    signer = SessionInput(signer_id=created["signers"][0]["id"])
    first = request_router.create_session(created["id"], signer, Response(), context)
    second = request_router.create_session(created["id"], signer, Response(), context)
    with sessions() as db:
        with pytest.raises(HTTPException):
            signing_service.resolve_session(db, first["session_token"], True)
        signing_service.resolve_session(db, second["session_token"], True)
    request_router.cancel_request(created["id"], context)
    with sessions() as db:
        with pytest.raises(HTTPException) as error:
            signing_service.resolve_session(db, second["session_token"], True)
        assert error.value.status_code == 409


def test_provider_vault_binds_tenant_provider_mode_and_version():
    from core_api.modules.enterprise.provider_vault import decrypt_configuration, encrypt_configuration
    tenant = uuid4()
    arguments = (tenant, "serproid", False, 1)
    secret = {"client_secret": "do-not-expose"}
    encrypted = encrypt_configuration(*arguments, secret)
    assert "do-not-expose" not in encrypted
    assert decrypt_configuration(*arguments, encrypted) == secret
    for changed in ((uuid4(), "serproid", False, 1), (tenant, "serpro_timestamp", False, 1),
                    (tenant, "serproid", True, 1), (tenant, "serproid", False, 2)):
        with pytest.raises(InvalidTag):
            decrypt_configuration(*changed, encrypted)


def test_download_integrity_is_checked_before_delivery():
    storage = type("Storage", (), {"get": lambda self, _: BytesIO(b"bad")})()
    with pytest.raises(HTTPException) as error:
        document_access.verified_content(storage, "key", sha256(b"good").hexdigest(), 4)
    assert error.value.status_code == 409


def test_missing_scanner_never_clears_quarantine(monkeypatch):
    monkeypatch.setattr(scanning.settings, "ENTERPRISE_CLAMAV_HOST", "")
    with pytest.raises(HTTPException) as error:
        scanning.scan_stream(BytesIO(b"pdf"))
    assert error.value.status_code == 503


def test_provider_storage_is_masked_versioned_and_has_no_fallback(workflow, monkeypatch):
    from types import SimpleNamespace
    from core_api.modules.enterprise import provider_router
    from core_api.modules.enterprise.provider_vault import load_configuration
    context, _, sessions, _ = workflow
    monkeypatch.setattr(provider_router, "SessionLocal", sessions)
    monkeypatch.setattr(provider_router, "require_enterprise", lambda *args: None)
    actor = SimpleNamespace(subject="admin")
    secret = {"client_secret": "company-secret", "client_id": str(uuid4()), "environment": "homologation"}
    saved = provider_router.save_configuration(context.tenant_id, True, "serproid", secret, actor)
    assert saved["status"] == "configured_unverified"
    assert "company-secret" not in str(saved)
    with sessions() as db:
        assert load_configuration(db, context.tenant_id, "serproid", True) == secret
        for tenant, sandbox in ((uuid4(), True), (context.tenant_id, False)):
            with pytest.raises(HTTPException):
                load_configuration(db, tenant, "serproid", sandbox)
    provider_router.save_configuration(context.tenant_id, True, "serproid", secret, actor)
    with sessions() as db:
        with pytest.raises(HTTPException) as error:
            load_configuration(db, context.tenant_id, "serproid", True, expected_version=1)
        assert error.value.status_code == 409
    provider_router.remove_provider(context.tenant_id, "serproid", True, actor)
    with sessions() as db:
        with pytest.raises(HTTPException):
            load_configuration(db, context.tenant_id, "serproid", True)


def prepare_live_provider(workflow, monkeypatch, mode, secret):
    from types import SimpleNamespace
    from core_api.modules.enterprise import provider_router, serproid_authorization
    context, _, sessions, storage = workflow
    context = replace(context, sandbox=False)
    with sessions.begin() as db:
        db.get(EnterpriseIntegration, context.integration_id).sandbox = False
    monkeypatch.setattr(provider_router, "SessionLocal", sessions)
    monkeypatch.setattr(serproid_authorization, "SessionLocal", sessions)
    monkeypatch.setattr(provider_router, "require_enterprise", lambda *args: None)
    provider_router.save_configuration(context.tenant_id, False, mode, secret, SimpleNamespace(subject="admin"))
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.write(output)
    document = document_router.persist_upload(context, output.getvalue(), "live.pdf", "application/pdf", "live-upload")
    monkeypatch.setattr(scanning, "scan_stream", lambda _: "ready")
    scanning.scan_document(context, document["id"])
    item = request_router.create_request(context, payload(document, mode), "live-request")
    request_router.open_request(item["id"], context)
    session = request_router.create_session(item["id"], SessionInput(signer_id=item["signers"][0]["id"]), Response(), context)
    command = ConsentCommand(consent=True, consent_version="rubrica-enterprise-evidence-v1", document_sha256=item["document_sha256"])
    return context, session, command, sessions, storage


def test_timestamp_uses_tenant_credentials_without_global_fallback(workflow, monkeypatch):
    from core_api.modules.signature_request import serpro_timestamp_service
    secret = {"consumer_key": "tenant-key", "consumer_secret": "tenant-secret"}
    _, session, command, sessions, _ = prepare_live_provider(workflow, monkeypatch, "serpro_timestamp", secret)
    calls = []

    def timestamp(pdf, *, credentials):
        calls.append(credentials)
        return pdf, {"provider": "test-double"}

    monkeypatch.setattr(serpro_timestamp_service, "apply_serpro_timestamp", timestamp)
    result = signing_service.sign_evidence(session["session_token"], False, command, ip_address="127.0.0.1", user_agent="test")
    assert result["simulated"] is False
    assert calls == [("tenant-key", "tenant-secret")]
    with sessions() as db:
        assert db.scalar(select(EnterpriseSignature)).provider_evidence == {"provider": "test-double"}


def test_serproid_state_is_one_use_encrypted_and_pkce_bound(workflow, monkeypatch):
    from urllib.parse import parse_qs, urlparse
    from core_api.modules.enterprise import serproid_authorization
    from core_api.modules.enterprise.entities import EnterpriseAuthorization
    client_id = str(uuid4())
    _, session, command, sessions, _ = prepare_live_provider(workflow, monkeypatch, "serproid",
        {"client_id": client_id, "client_secret": "tenant-secret", "environment": "homologation"})
    monkeypatch.setattr(serproid_authorization.settings, "ENTERPRISE_SERPROID_TRUST_ROOTS_FILE", "test-trust.pem")
    monkeypatch.setattr(serproid_authorization, "_load_trust_roots", lambda _: [])
    result = serproid_authorization.start(session["session_token"], False, command,
                                         ip_address="127.0.0.1", user_agent="test")
    url = urlparse(result["authorization_url"])
    assert url.hostname == "hom.serproid.serpro.gov.br"
    query = parse_qs(url.query)
    assert query["client_id"] == [client_id]
    assert query["code_challenge_method"] == ["S256"]
    assert session["session_token"] not in result["authorization_url"]
    with sessions() as db:
        state = db.scalar(select(EnterpriseAuthorization))
        assert session["session_token"] not in state.encrypted_attempt
        assert query["state"][0] not in state.state_digest
    _, attempt = serproid_authorization.consume_attempt(query["state"][0])
    assert attempt["session_secret"] == session["session_token"]
    with pytest.raises(HTTPException) as error:
        serproid_authorization.consume_attempt(query["state"][0])
    assert error.value.status_code == 400


@pytest.mark.parametrize(("result", "expected"), [(b"stream: OK\x00", "ready"), (b"stream: Eicar FOUND\x00", "rejected")])
def test_scanner_protocol_requires_explicit_result(monkeypatch, result, expected):
    class Scanner:
        def __init__(self):
            self.sent = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def sendall(self, data):
            self.sent.append(data)
        def recv(self, _):
            return result
    scanner = Scanner()
    monkeypatch.setattr(scanning.settings, "ENTERPRISE_CLAMAV_HOST", "internal-scanner")
    monkeypatch.setattr(scanning.socket, "create_connection", lambda *args, **kwargs: scanner)
    assert scanning.scan_stream(BytesIO(b"pdf")) == expected
    assert scanner.sent == [b"zINSTREAM\x00", b"\x00\x00\x00\x03pdf", b"\x00\x00\x00\x00"]
