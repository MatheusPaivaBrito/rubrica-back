from fastapi import APIRouter, Depends, Query, Request, Response, status
from uuid import UUID

from core_api.modules.document.document_schema import DocumentCreate, DocumentRead
from core_api.modules.document.pdf_validation import validate_pdf_upload
from core_api.infrastructure.settings import settings
from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.infrastructure.content_disposition import pdf_content_disposition
from core_api.modules.signature_request.database_workflow_service import database_workflow_service as workflow_service
from core_api.modules.signature_request.workflow_service import WorkflowError


router = APIRouter(prefix="/documents")


@router.get("", response_model=list[DocumentRead], tags=["documents - query"])
async def list_documents(context: AuthContext = Depends(require_permission("documents:read"))) -> list[DocumentRead]:
    return workflow_service.list_documents(context.subject)


@router.get("/{document_id}", response_model=DocumentRead, tags=["documents - query"])
async def get_document(document_id: UUID, context: AuthContext = Depends(require_permission("documents:read"))) -> DocumentRead:
    return workflow_service.get_document(document_id, context.subject)

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["documents - command"])
async def delete_document(document_id: UUID, force: bool = Query(False), context: AuthContext = Depends(require_permission("documents:write"))) -> Response:
    workflow_service.delete_document(document_id, context.subject, force=force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{document_id}/download", tags=["documents - query"])
async def download_document(document_id: UUID, version: int | None = None, context: AuthContext = Depends(require_permission("documents:read"))) -> Response:
    metadata, content = workflow_service.get_content(document_id, version, context.subject)
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": pdf_content_disposition(metadata.original_filename, attachment=True), "X-Content-Type-Options": "nosniff", "X-Document-SHA256": metadata.sha256})


@router.get("/{document_id}/preview", tags=["documents - query"])
async def preview_document(document_id: UUID, version: int | None = None, context: AuthContext = Depends(require_permission("documents:read"))) -> Response:
    metadata, content = workflow_service.get_content(document_id, version, context.subject)
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": pdf_content_disposition(metadata.original_filename), "X-Content-Type-Options": "nosniff", "X-Document-SHA256": metadata.sha256})


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED, tags=["documents - command"])
async def upload_document(
    request: Request,
    organization_id: str = Query(min_length=1),
    title: str = Query(min_length=1),
    filename: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(require_permission("documents:write")),
) -> DocumentRead:
    content = await _read_document_body(request)
    content_type = request.headers.get("content-type", "")
    validate_pdf_upload(content, filename=filename, content_type=content_type)
    payload = DocumentCreate(organization_id=organization_id, title=title, original_filename=filename, content_type="application/pdf", created_by=context.subject)
    return workflow_service.create_document(payload, content)


@router.post("/{document_id}/versions", response_model=DocumentRead, tags=["documents - command"])
async def create_version(
    document_id: UUID,
    request: Request,
    filename: str = Query(min_length=1, max_length=120),
    context: AuthContext = Depends(require_permission("documents:write")),
) -> DocumentRead:
    content = await _read_document_body(request)
    validate_pdf_upload(content, filename=filename, content_type=request.headers.get("content-type", ""))
    return workflow_service.add_version(document_id, filename=filename, content_type="application/pdf", actor_id=context.subject, content=content)


async def _read_document_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.DOCUMENT_MAX_SIZE_BYTES:
                raise WorkflowError("Document exceeds the allowed size", 413)
        except ValueError as exc:
            raise WorkflowError("Invalid Content-Length header") from exc
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > settings.DOCUMENT_MAX_SIZE_BYTES:
            raise WorkflowError("Document exceeds the allowed size", 413)
    return bytes(body)
