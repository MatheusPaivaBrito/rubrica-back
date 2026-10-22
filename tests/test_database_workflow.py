import os
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from pypdf import PdfReader, PdfWriter

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.billing.billing_service import billing_service
from core_api.modules.document.document_entity import DocumentEntity
from core_api.modules.document.document_schema import DocumentCreate
from core_api.modules.document.storage import LocalDocumentStorage
from core_api.modules.signature_request.database_workflow_service import DatabaseSignatureWorkflowService
from core_api.modules.signature_request.signature_request_entity import (
    SignatureEntity,
    SignatureOperationEntity,
    SignatureRequestEntity,
)
from core_api.modules.signature_request.workflow_schema import RequestStatus, SignatureRequestCreate, SignerCreate, StampPosition
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.signature_request.workflow_service import WorkflowError
from shared_kernel.time.datetime_service import DateTimeService


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
                    status="not_configured",
                )
            )
        source = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.write(source)
        original = source.getvalue()
        document = service.create_document(DocumentCreate(organization_id=organization, title="Smoke", original_filename="smoke.pdf", content_type="application/pdf", created_by="operator"), original)
        request = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
        service.add_signer(request.id, SignerCreate(name="Database User", email="database@example.com"), "operator")
        service.add_signer(request.id, SignerCreate(name="Second User", email="second@example.com"), "operator")
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
        assert service.signing_context(token, "database@example.com").stamp == stamp
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
            assert billing_account.signatures_used == 2
            assert billing_account.free_signatures_limit == 5
    finally:
        pass
