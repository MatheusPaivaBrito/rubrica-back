import os
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.document.document_entity import DocumentEntity, DocumentVersionEntity
from core_api.modules.document.document_schema import DocumentCreate
from core_api.modules.document.storage import LocalDocumentStorage
from core_api.modules.signature_request.database_workflow_service import DatabaseSignatureWorkflowService
from core_api.modules.signature_request.signature_request_entity import AuditEventEntity, SignatureEntity, SignatureRequestEntity, SignerEntity
from core_api.modules.signature_request.workflow_schema import RequestStatus, SignatureRequestCreate, SignerCreate
from shared_kernel.time.datetime_service import DateTimeService


pytestmark = pytest.mark.skipif(os.getenv("RUBRICA_DATABASE_TESTS") != "1", reason="requires Rubrica PostgreSQL")


def test_database_workflow_round_trip(tmp_path: Path) -> None:
    service = DatabaseSignatureWorkflowService(LocalDocumentStorage(tmp_path / "objects"))
    organization = "database-smoke-test"
    document_id: int | None = None
    try:
        document = service.create_document(DocumentCreate(organization_id=organization, title="Smoke", original_filename="smoke.pdf", content_type="application/pdf", created_by="operator"), b"database workflow")
        document_id = int(document.id)
        request = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
        invitation = service.add_signer(request.id, SignerCreate(name="Database User", email="database@example.com"), "operator")
        service.open_request(request.id, "operator")
        service.sign(invitation.signing_url.rsplit("/", maxsplit=1)[-1], "database@example.com", True)

        assert service.get_request(request.id).status == RequestStatus.COMPLETED
        assert service.get_content(document.id)[1] == b"database workflow"
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
