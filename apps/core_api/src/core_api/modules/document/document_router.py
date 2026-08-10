from fastapi import APIRouter, Body, Depends, Query, Response, status

from core_api.modules.document.document_schema import DocumentCreate, DocumentRead
from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.modules.signature_request.database_workflow_service import database_workflow_service as workflow_service


router = APIRouter(prefix="/documents")


@router.get("", response_model=list[DocumentRead], tags=["documents - query"])
async def list_documents(_context: AuthContext = Depends(require_permission("documents:read"))) -> list[DocumentRead]:
    return workflow_service.list_documents()


@router.get("/{document_id}", response_model=DocumentRead, tags=["documents - query"])
async def get_document(document_id: str, _context: AuthContext = Depends(require_permission("documents:read"))) -> DocumentRead:
    return workflow_service.get_document(document_id)

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["documents - command"])
async def delete_document(document_id: str, context: AuthContext = Depends(require_permission("documents:write"))) -> Response:
    workflow_service.delete_document(document_id, context.subject)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{document_id}/download", tags=["documents - query"])
async def download_document(document_id: str, version: int | None = None, _context: AuthContext = Depends(require_permission("documents:read"))) -> Response:
    metadata, content = workflow_service.get_content(document_id, version)
    return Response(content, media_type=metadata.content_type, headers={"Content-Disposition": f'attachment; filename="{metadata.original_filename}"', "X-Document-SHA256": metadata.sha256})


@router.get("/{document_id}/preview", tags=["documents - query"])
async def preview_document(document_id: str, version: int | None = None, _context: AuthContext = Depends(require_permission("documents:read"))) -> Response:
    metadata, content = workflow_service.get_content(document_id, version)
    return Response(content, media_type=metadata.content_type, headers={"Content-Disposition": f'inline; filename="{metadata.original_filename}"', "X-Document-SHA256": metadata.sha256})


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED, tags=["documents - command"])
async def upload_document(
    content: bytes = Body(media_type="application/octet-stream"),
    organization_id: str = Query(min_length=1),
    title: str = Query(min_length=1),
    filename: str = Query(min_length=1),
    content_type: str = Query(default="application/octet-stream"),
    context: AuthContext = Depends(require_permission("documents:write")),
) -> DocumentRead:
    payload = DocumentCreate(organization_id=organization_id, title=title, original_filename=filename, content_type=content_type, created_by=context.subject)
    return workflow_service.create_document(payload, content)


@router.post("/{document_id}/versions", response_model=DocumentRead, tags=["documents - command"])
async def create_version(
    document_id: str,
    content: bytes = Body(media_type="application/octet-stream"),
    filename: str = Query(min_length=1),
    content_type: str = Query(default="application/octet-stream"),
    context: AuthContext = Depends(require_permission("documents:write")),
) -> DocumentRead:
    return workflow_service.add_version(document_id, filename=filename, content_type=content_type, actor_id=context.subject, content=content)
