import asyncio
from io import BytesIO

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter
from sqlalchemy import func, or_, select
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from core_api.infrastructure.settings import settings
from core_api.modules.document.document_entity import DocumentEntity
from core_api.modules.document.document_schema import DocumentCreate
from core_api.modules.document.document_router import _read_document_body
from core_api.modules.document.pdf_validation import validate_pdf_upload
from core_api.modules.document.storage import LocalDocumentStorage
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import TenantEntity


def pdf_bytes(*, javascript: bool = False, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    if javascript:
        writer.add_js("app.alert('unsafe')")
    if encrypted:
        writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_accepts_a_passive_pdf() -> None:
    validate_pdf_upload(pdf_bytes(), filename="contract.pdf", content_type="application/pdf")


def test_rejects_document_filenames_longer_than_120_characters() -> None:
    with pytest.raises(ValidationError):
        DocumentCreate(
            organization_id="acme",
            title="Agreement",
            original_filename=f"{'a' * 117}.pdf",
            content_type="application/pdf",
            created_by="operator",
        )


@pytest.mark.parametrize(
    ("content", "filename", "content_type"),
    [
        (b"#!/bin/sh\necho owned", "contract.pdf", "application/pdf"),
        (b"<script>alert(1)</script>", "contract.pdf", "application/pdf"),
        (pdf_bytes(), "contract.pdf.sh", "application/pdf"),
        (pdf_bytes(), "../contract.pdf", "application/pdf"),
        (pdf_bytes(), "contract.pdf", "text/html"),
    ],
)
def test_rejects_disguised_files(content: bytes, filename: str, content_type: str) -> None:
    with pytest.raises(WorkflowError):
        validate_pdf_upload(content, filename=filename, content_type=content_type)


@pytest.mark.parametrize("content", [pdf_bytes(javascript=True), pdf_bytes(encrypted=True)])
def test_rejects_active_or_encrypted_pdfs(content: bytes) -> None:
    with pytest.raises(WorkflowError):
        validate_pdf_upload(content, filename="contract.pdf", content_type="application/pdf")


def test_streaming_reader_stops_above_the_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DOCUMENT_MAX_SIZE_BYTES", 8)
    chunks = iter([b"12345", b"67890", b""])

    async def receive():
        body = next(chunks)
        return {"type": "http.request", "body": body, "more_body": bool(body)}

    request = Request({"type": "http", "method": "POST", "path": "/documents", "headers": []}, receive)
    with pytest.raises(WorkflowError) as error:
        asyncio.run(_read_document_body(request))
    assert error.value.status_code == 413


def test_storage_uses_an_opaque_non_executable_file(tmp_path) -> None:
    storage = LocalDocumentStorage(tmp_path / "documents")
    key, size = storage.put(BytesIO(b"#!/bin/sh\necho owned"), filename="attack.sh")
    stored = storage.root / key
    assert size == stored.stat().st_size
    assert key.isalnum() and "." not in key
    assert stored.stat().st_mode & 0o777 == 0o600
    assert storage.root.stat().st_mode & 0o777 == 0o700


def test_user_input_is_bound_in_representative_database_queries() -> None:
    attack = "' OR 1=1; DROP TABLE documents; --"
    statements = [
        select(DocumentEntity).where(DocumentEntity.created_by == attack),
        select(TenantEntity).where(or_(TenantEntity.slug == attack, func.lower(TenantEntity.name) == attack.lower())),
    ]
    for statement in statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        assert attack not in str(compiled)
        assert attack in compiled.params.values()
