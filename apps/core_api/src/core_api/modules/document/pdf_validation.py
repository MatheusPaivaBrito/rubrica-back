from __future__ import annotations

from io import BytesIO
from pathlib import PurePath
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from core_api.infrastructure.settings import settings
from core_api.modules.signature_request.workflow_service import WorkflowError


_ACTIVE_PDF_KEYS = {
    "/AA",
    "/EmbeddedFile",
    "/EmbeddedFiles",
    "/ImportData",
    "/JavaScript",
    "/JS",
    "/Launch",
    "/OpenAction",
    "/RichMedia",
    "/SubmitForm",
    "/XFA",
}


def validate_pdf_upload(content: bytes, *, filename: str, content_type: str) -> None:
    """Reject disguised, malformed, encrypted, or active PDFs before storage."""
    if not content:
        raise WorkflowError("Document content cannot be empty")
    if len(content) > settings.DOCUMENT_MAX_SIZE_BYTES:
        raise WorkflowError("Document exceeds the allowed size", 413)
    if content_type.split(";", 1)[0].strip().lower() != "application/pdf":
        raise WorkflowError("Only PDF documents are accepted", 415)
    if PurePath(filename).name != filename or "\\" in filename or not filename.lower().endswith(".pdf") or any(ord(char) < 32 for char in filename):
        raise WorkflowError("Invalid PDF filename")
    if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
        raise WorkflowError("File content is not a PDF", 415)

    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise WorkflowError("Encrypted PDFs are not supported")
        page_count = len(reader.pages)
        if page_count < 1 or page_count > settings.DOCUMENT_MAX_PAGES:
            raise WorkflowError("PDF page count is outside the allowed range")
        for page in reader.pages:
            if float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0:
                raise WorkflowError("PDF contains an invalid page")
        _reject_active_content(reader.trailer)
    except WorkflowError:
        raise
    except (PdfReadError, ValueError, TypeError, RecursionError, KeyError, AssertionError) as exc:
        raise WorkflowError("PDF is malformed or unsupported") from exc


def _reject_active_content(root: Any) -> None:
    pending = [root]
    visited: set[tuple[int, int] | int] = set()
    inspected = 0
    while pending:
        value = pending.pop()
        inspected += 1
        if inspected > 100_000:
            raise WorkflowError("PDF structure is too complex")
        if isinstance(value, IndirectObject):
            identity: tuple[int, int] | int = (value.idnum, value.generation)
            if identity in visited:
                continue
            visited.add(identity)
            try:
                pending.append(value.get_object())
            except Exception as exc:
                raise WorkflowError("PDF contains an invalid object") from exc
        elif isinstance(value, DictionaryObject):
            for key, child in value.items():
                if str(key) in _ACTIVE_PDF_KEYS:
                    raise WorkflowError("PDF contains active or embedded content")
                pending.append(child)
        elif isinstance(value, ArrayObject):
            pending.extend(value)
