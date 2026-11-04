import asyncio
from io import BytesIO
from uuid import uuid4

from fastapi import HTTPException
from pypdf import PdfWriter
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core_api.modules.enterprise import document_router as uploads
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseDocument
from core_api.modules.enterprise.machine_context import MachineContext


def test_stream_limit_applies_without_reliable_content_length(monkeypatch):
    monkeypatch.setattr(uploads, "MAX_PDF_BYTES", 4)

    class Body:
        headers = {"content-length": "1"}

        async def stream(self):
            yield b"123"
            yield b"45"

    with pytest.raises(HTTPException) as error:
        asyncio.run(uploads.read_pdf_body(Body()))
    assert error.value.status_code == 413


def test_upload_is_idempotent_quarantined_and_compartment_scoped(monkeypatch, tmp_path):
    from core_api.modules.document.storage import LocalDocumentStorage
    engine = create_engine("sqlite://")
    import core_api.infrastructure.database.loader  # noqa: F401
    from core_api.infrastructure.database.connection import Base
    from core_api.modules.billing.billing_entity import BillingAccountEntity
    from core_api.modules.enterprise.entities import EnterpriseIntegration
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(uploads, "SessionLocal", sessions)
    storage = LocalDocumentStorage(tmp_path)
    monkeypatch.setattr(uploads, "configured_document_storage", lambda _: storage)
    monkeypatch.setattr(uploads.tenant_service, "_audit", lambda *args: None)
    tenant, integration, compartment = uuid4(), uuid4(), uuid4()
    context = MachineContext(tenant, integration, compartment, "public-token-id", True)
    with sessions.begin() as db:
        db.add(BillingAccountEntity(tenant_id=tenant, current_product_code="rubrica_enterprise", status="active"))
        db.add(EnterpriseIntegration(id=integration, tenant_id=tenant, name="Test", environment="development", sandbox=True, created_by="admin"))
        db.add(EnterpriseCompartment(id=compartment, integration_id=integration, name="customer"))
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    content = BytesIO()
    writer.write(content)
    args = (context, content.getvalue(), "test.pdf", "application/pdf", "upload-1")
    first = uploads.persist_upload(*args)
    assert first["status"] == "quarantined"
    assert uploads.persist_upload(*args) == first
    with pytest.raises(HTTPException) as error:
        uploads.persist_upload(context, content.getvalue(), "changed.pdf", "application/pdf", "upload-1")
    assert error.value.status_code == 409
    wrong = MachineContext(tenant, uuid4(), compartment, "other", True)
    with pytest.raises(HTTPException) as error:
        uploads.persist_upload(wrong, *args[1:])
    assert error.value.status_code == 404
    with sessions() as db:
        item = db.scalar(select(EnterpriseDocument))
        assert "/enterprise/sandbox/" in item.storage_key
        assert item.token_public_id == "public-token-id"
        with storage.get(item.storage_key) as stored:
            assert stored.read() == content.getvalue()


def test_sandbox_uses_distinct_encryption_context():
    from core_api.modules.document.storage import R2DocumentStorage
    key = "tenants/tenant/enterprise/sandbox/integration/compartment/document/object"
    sandbox = R2DocumentStorage._contexts(key)
    live = R2DocumentStorage._contexts(key.replace("sandbox", "live"))
    assert sandbox != live
    assert sandbox[0] != "legacy-unscoped"


def test_machine_context_requires_header_not_user_cookie():
    from core_api.modules.enterprise.machine_context import require_machine
    request = type("Request", (), {"headers": {}, "cookies": {"access_token": "human"}})()
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_machine("documents:create")(request, uuid4()))
    assert error.value.status_code == 401


def test_binding_checks_integration_contract_and_compartment():
    from core_api.modules.enterprise.machine_context import AuthClaims, authorize_binding
    from types import SimpleNamespace
    claims = AuthClaims(tenant_id=uuid4(), integration_id=uuid4(), public_id="id",
                        environment="development", sandbox=True, scopes={"documents:create"})
    from datetime import UTC, datetime
    account = SimpleNamespace(tenant_id=claims.tenant_id, current_product_code="rubrica_enterprise", status="active",
        cancel_at_period_end=False, usage_period_starts_at=datetime.now(UTC), created_at=datetime.now(UTC))
    for rows, status in (([None], 403), ([object(), None], 403), ([object(), account, None, None], 404)):
        responses = iter(rows)
        database = SimpleNamespace(scalar=lambda _: next(responses))
        with pytest.raises(HTTPException) as error:
            authorize_binding(database, claims, uuid4())
        assert error.value.status_code == status
    responses = iter([object(), account, None, object()])
    compartment_id = uuid4()
    context = authorize_binding(SimpleNamespace(scalar=lambda _: next(responses)), claims, compartment_id)
    assert context.tenant_id == claims.tenant_id
    assert context.integration_id == claims.integration_id
    assert context.compartment_id == compartment_id
