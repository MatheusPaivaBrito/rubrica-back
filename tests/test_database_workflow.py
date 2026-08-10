import os
from datetime import timedelta
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from pypdf import PdfReader, PdfWriter

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.document.document_entity import DocumentEntity, DocumentVersionEntity
from core_api.modules.document.document_schema import DocumentCreate
from core_api.modules.document.storage import LocalDocumentStorage
from core_api.modules.signature_request.database_workflow_service import DatabaseSignatureWorkflowService
from core_api.modules.signature_request.signature_request_entity import AuditEventEntity, SignatureEntity, SignatureRequestEntity, SignerEntity
from core_api.modules.signature_request.workflow_schema import RequestStatus, SignatureRequestCreate, SignerCreate, StampPosition
from shared_kernel.time.datetime_service import DateTimeService


pytestmark = pytest.mark.skipif(os.getenv("RUBRICA_DATABASE_TESTS") != "1", reason="requires Rubrica PostgreSQL")


def test_database_workflow_round_trip(tmp_path: Path) -> None:
    service = DatabaseSignatureWorkflowService(LocalDocumentStorage(tmp_path / "objects"))
    organization = "database-smoke-test"
    document_id: int | None = None
    try:
        source = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.write(source)
        original = source.getvalue()
        document = service.create_document(DocumentCreate(organization_id=organization, title="Smoke", original_filename="smoke.pdf", content_type="application/pdf", created_by="operator"), original)
        document_id = int(document.id)
        request = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
        service.add_signer(request.id, SignerCreate(name="Database User", email="database@example.com"), "operator")
        service.open_request(request.id, "operator")
        link = service.create_signing_link(request.id, "operator")
        token = link.signing_url.rsplit("/", maxsplit=1)[-1]
        stamp = StampPosition(page=1, x=0.65, y=0.8)
        service.sign(token, "database@example.com", True, stamp)

        assert service.get_request(request.id).status == RequestStatus.COMPLETED
        assert service.get_content(document.id)[1] == original
        with SessionLocal.begin() as db:
            persisted_request = db.scalar(select(SignatureRequestEntity).where(SignatureRequestEntity.id == int(request.id)))
            persisted_request.expires_at = DateTimeService.utc_now() - timedelta(days=730)
        assert service.signing_context(token, "database@example.com").stamp == stamp
        assert service.signing_signed_document(token, "database@example.com")[2].startswith(b"%PDF")
        assert service.get_signing_link(request.id).signing_url == link.signing_url
        historical_link = service.create_signing_link(request.id, "administrator")
        historical_token = historical_link.signing_url.rsplit("/", maxsplit=1)[-1]
        assert service.signing_signed_document(historical_token, "database@example.com")[2].startswith(b"%PDF")
        administrator_view = service.signing_context(historical_token, "admin@example.local", administrator=True)
        assert administrator_view.viewer_mode == "administrator"
        assert administrator_view.request.status == RequestStatus.COMPLETED
        assert service.signing_signed_document(historical_token, "admin@example.local", administrator=True)[2].startswith(b"%PDF")
        signer_view = service.signing_context(historical_token, "database@example.com", administrator=True)
        assert signer_view.viewer_mode == "signer"
        filename, artifact_hash, artifact = service.signed_document(request.id)
        assert filename.endswith("signed.pdf")
        assert artifact_hash
        assert artifact.startswith(b"%PDF")
        artifact_metadata = PdfReader(BytesIO(artifact)).metadata
        assert artifact_metadata.get("/RubricaEvidenceJSON")
        evidence = service.signature_evidence(request.id)
        assert evidence[0].evidence_sha256
        assert evidence[0].subject_hmac_sha256 != "database@example.com"
        assert "signature.completed" in [event.action for event in service.audit_events(request.id)]
    finally:
        if document_id is not None:
            with SessionLocal.begin() as db:
                request_ids = list(db.scalars(select(SignatureRequestEntity.id).where(SignatureRequestEntity.document_id == document_id)).all())
                signer_ids = list(db.scalars(select(SignerEntity.id).where(SignerEntity.signature_request_id.in_(request_ids))).all()) if request_ids else []
                if request_ids:
                    db.execute(delete(AuditEventEntity).where(AuditEventEntity.signature_request_id.in_(request_ids)))
                    db.execute(delete(SignatureEntity).where(SignatureEntity.signature_request_id.in_(request_ids)))
                if signer_ids:
                    db.execute(delete(SignerEntity).where(SignerEntity.id.in_(signer_ids)))
                if request_ids:
                    db.execute(delete(SignatureRequestEntity).where(SignatureRequestEntity.id.in_(request_ids)))
                db.execute(delete(AuditEventEntity).where(AuditEventEntity.entity_type == "document", AuditEventEntity.entity_id == str(document_id)))
                db.execute(delete(DocumentVersionEntity).where(DocumentVersionEntity.document_id == document_id))
                db.execute(delete(DocumentEntity).where(DocumentEntity.id == document_id))
