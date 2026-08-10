from datetime import timedelta
from pathlib import Path

import pytest

from core_api.modules.document.document_schema import DocumentCreate
from core_api.modules.document.storage import LocalDocumentStorage
from core_api.modules.signature_request.workflow_schema import (
    RequestStatus,
    SignatureRequestCreate,
    SignerCreate,
    SignerStatus,
    StampPosition,
)
from core_api.modules.signature_request.workflow_service import SignatureWorkflowService, WorkflowError
from shared_kernel.time.datetime_service import DateTimeService


@pytest.fixture
def service(tmp_path: Path) -> SignatureWorkflowService:
    return SignatureWorkflowService(LocalDocumentStorage(tmp_path / "objects"))


def invitation_token(signing_url: str) -> str:
    return signing_url.rsplit("/", maxsplit=1)[-1]


STAMP = StampPosition(page=1, x=0.72, y=0.84)


def test_full_signature_flow_is_tracked(service: SignatureWorkflowService) -> None:
    content = b"immutable agreement"
    document = service.create_document(
        DocumentCreate(organization_id="acme", title="Agreement", original_filename="agreement.pdf", content_type="application/pdf", created_by="operator-1"),
        content,
    )
    request = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(days=1), created_by="operator-1"))
    service.add_signer(request.id, SignerCreate(name="Ada", email="ada@example.com"), "operator-1")
    opened = service.open_request(request.id, "operator-1")
    token = invitation_token(service.create_signing_link(request.id, "operator-1").signing_url)
    service.view(token, "ada@example.com")
    signer = service.sign(token, "ada@example.com", True, STAMP)

    assert opened.status == RequestStatus.OPEN
    assert signer.status == SignerStatus.SIGNED
    assert service.get_request(request.id).status == RequestStatus.COMPLETED
    assert service.get_request(request.id).signed_count == 1
    assert service.get_content(document.id)[1] == content
    assert service.signing_context(token, "ada@example.com").stamp == STAMP
    assert [event.action for event in service.audit_events(request.id)] == [
        "signature_request.created", "signer.link_created", "signature_request.opened", "signature_request.link_created",
        "document.viewed", "signature.completed", "signature_request.completed",
    ]


def test_identity_and_duplicate_signature_are_rejected(service: SignatureWorkflowService) -> None:
    document = service.create_document(DocumentCreate(organization_id="acme", title="NDA", original_filename="nda.pdf", content_type="application/pdf", created_by="operator"), b"nda")
    request = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
    service.add_signer(request.id, SignerCreate(name="Signer", email="signer@example.com"), "operator")
    service.open_request(request.id, "operator")
    token = invitation_token(service.create_signing_link(request.id, "operator").signing_url)

    with pytest.raises(WorkflowError, match="does not match"):
        service.sign(token, "intruder@example.com", True, STAMP)
    service.sign(token, "signer@example.com", True, STAMP)
    with pytest.raises(WorkflowError):
        service.sign(token, "signer@example.com", True, STAMP)


def test_new_version_is_blocked_after_request_is_open(service: SignatureWorkflowService) -> None:
    document = service.create_document(DocumentCreate(organization_id="acme", title="NDA", original_filename="nda.pdf", content_type="application/pdf", created_by="operator"), b"v1")
    request = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
    service.add_signer(request.id, SignerCreate(name="Signer", email="signer@example.com"), "operator")
    service.open_request(request.id, "operator")

    with pytest.raises(WorkflowError, match="frozen"):
        service.add_version(document.id, filename="nda-v2.pdf", content_type="application/pdf", actor_id="operator", content=b"v2")


def test_document_soft_delete_behavior_is_blocked_by_active_request(service: SignatureWorkflowService) -> None:
    standalone = service.create_document(DocumentCreate(organization_id="acme", title="Delete me", original_filename="delete.pdf", content_type="application/pdf", created_by="operator"), b"pdf")
    service.delete_document(standalone.id, "operator")
    assert service.list_documents() == []

    linked = service.create_document(DocumentCreate(organization_id="acme", title="Linked", original_filename="linked.pdf", content_type="application/pdf", created_by="operator"), b"pdf")
    service.create_request(SignatureRequestCreate(document_id=linked.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
    with pytest.raises(WorkflowError, match="active signature request"):
        service.delete_document(linked.id, "operator")


def test_revoked_link_cannot_be_used(service: SignatureWorkflowService) -> None:
    document = service.create_document(DocumentCreate(organization_id="acme", title="NDA", original_filename="nda.pdf", content_type="application/pdf", created_by="operator"), b"nda")
    request = service.create_request(SignatureRequestCreate(document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(hours=1), created_by="operator"))
    invitation = service.add_signer(request.id, SignerCreate(name="Signer", email="signer@example.com"), "operator")
    service.open_request(request.id, "operator")
    token = invitation_token(service.create_signing_link(request.id, "operator").signing_url)
    service.revoke_signer_link(request.id, invitation.id, "operator")

    with pytest.raises(WorkflowError, match="revoked"):
        service.sign(token, "signer@example.com", True, STAMP)
