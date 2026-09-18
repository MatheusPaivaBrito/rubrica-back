import asyncio
from types import SimpleNamespace

from fastapi import Response

from core_api.infrastructure.auth_context import AuthContext
from core_api.infrastructure.content_disposition import pdf_content_disposition
from core_api.modules.signature_request import signature_request_router


def test_unicode_pdf_filename_is_safe_for_http_response_headers() -> None:
    # Combining accents are common in filenames from Apple devices and cannot
    # be encoded by Starlette's Latin-1 response header path.
    header = pdf_content_disposition("Proposta JOA\u0303O VÍTOR.pdf")
    response = Response(b"%PDF", headers={"Content-Disposition": header})

    assert response.headers["content-disposition"] == (
        'inline; filename="documento.pdf"; '
        "filename*=UTF-8''Proposta%20JOA%CC%83O%20V%C3%8DTOR.pdf"
    )


def test_ascii_filename_and_attachment_are_preserved() -> None:
    header = pdf_content_disposition("cnpj.pdf", attachment=True)

    assert header == 'attachment; filename="cnpj.pdf"; filename*=UTF-8\'\'cnpj.pdf'


def test_signing_document_route_returns_unicode_filename_without_server_error(monkeypatch) -> None:
    filename = "Proposta JOA\u0303O.pdf"
    metadata = SimpleNamespace(original_filename=filename, content_type="application/pdf", sha256="digest")
    monkeypatch.setattr(
        signature_request_router.workflow_service,
        "signing_document",
        lambda token, subject, administrator=False: (metadata, b"%PDF-1.4\n"),
    )
    context = AuthContext(subject="signer@example.com", roles=frozenset(), permission_keys=frozenset())

    response = asyncio.run(signature_request_router.signing_document("token", context))

    assert response.status_code == 200
    assert response.body.startswith(b"%PDF")
    assert "JOA%CC%83O.pdf" in response.headers["content-disposition"]
