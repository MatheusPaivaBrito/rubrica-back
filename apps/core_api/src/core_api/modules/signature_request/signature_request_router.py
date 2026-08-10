from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from core_api.infrastructure.auth_context import AuthContext, authenticated_context, require_permission
from core_api.modules.signature_request.workflow_schema import (
    AuditEventRead,
    SignCommand,
    SignatureRequestCreate,
    SignatureRequestInput,
    SignatureRequestRead,
    SignatureEvidenceRead,
    SignerCreate,
    SigningLinkRead,
    SignerRead,
    SigningRead,
)
from core_api.modules.signature_request.database_workflow_service import database_workflow_service as workflow_service


router = APIRouter()


async def administrator_context(context: AuthContext = Depends(authenticated_context)) -> AuthContext:
    if "signature_admin" not in context.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return context


@router.get("/signature-requests", response_model=list[SignatureRequestRead], tags=["signature requests - query"])
async def list_requests(_context: AuthContext = Depends(require_permission("signature_requests:read"))) -> list[SignatureRequestRead]:
    return workflow_service.list_requests()


@router.get("/signature-requests/{request_id}", response_model=SignatureRequestRead, tags=["signature requests - query"])
async def get_request(request_id: str, _context: AuthContext = Depends(require_permission("signature_requests:read"))) -> SignatureRequestRead:
    return workflow_service.get_request(request_id)


@router.post("/signature-requests", response_model=SignatureRequestRead, status_code=status.HTTP_201_CREATED, tags=["signature requests - command"])
async def create_request(payload: SignatureRequestInput, context: AuthContext = Depends(require_permission("signature_requests:write"))) -> SignatureRequestRead:
    return workflow_service.create_request(SignatureRequestCreate(**payload.model_dump(), created_by=context.subject))


@router.get("/signature-requests/{request_id}/signers", response_model=list[SignerRead], tags=["signature requests - query"])
async def list_signers(request_id: str, _context: AuthContext = Depends(require_permission("signature_requests:read"))) -> list[SignerRead]:
    return workflow_service.list_signers(request_id)


@router.post("/signature-requests/{request_id}/signers", response_model=SignerRead, status_code=status.HTTP_201_CREATED, tags=["signature requests - command"])
async def add_signer(request_id: str, payload: SignerCreate, context: AuthContext = Depends(require_permission("signature_requests:write"))) -> SignerRead:
    return workflow_service.add_signer(request_id, payload, context.subject)

@router.post("/signature-requests/{request_id}/signing-link", response_model=SigningLinkRead, tags=["signature requests - command"])
async def create_signing_link(request_id: str, context: AuthContext = Depends(require_permission("signature_requests:write"))) -> SigningLinkRead:
    return workflow_service.create_signing_link(request_id, context.subject)


@router.get("/signature-requests/{request_id}/signing-link", response_model=SigningLinkRead, tags=["signature requests - query"])
async def get_signing_link(request_id: str, _context: AuthContext = Depends(administrator_context)) -> SigningLinkRead:
    return workflow_service.get_signing_link(request_id)


@router.get("/signature-requests/{request_id}/evidence", response_model=list[SignatureEvidenceRead], tags=["audit - query"])
async def signature_evidence(request_id: str, _context: AuthContext = Depends(administrator_context)) -> list[SignatureEvidenceRead]:
    return workflow_service.signature_evidence(request_id)


@router.get("/signature-requests/{request_id}/signed-document", tags=["signature requests - query"])
async def signed_document(request_id: str, _context: AuthContext = Depends(administrator_context)) -> Response:
    filename, digest, content = workflow_service.signed_document(request_id)
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"', "X-Signed-Document-SHA256": digest})


@router.post("/signature-requests/{request_id}/signers/{signer_id}/revoke", response_model=SignerRead, tags=["signature requests - command"])
async def revoke_signer_link(request_id: str, signer_id: str, context: AuthContext = Depends(require_permission("signature_requests:write"))) -> SignerRead:
    return workflow_service.revoke_signer_link(request_id, signer_id, context.subject)


@router.post("/signature-requests/{request_id}/open", response_model=SignatureRequestRead, tags=["signature requests - command"])
async def open_request(request_id: str, context: AuthContext = Depends(require_permission("signature_requests:write"))) -> SignatureRequestRead:
    return workflow_service.open_request(request_id, context.subject)


@router.post("/signature-requests/{request_id}/cancel", response_model=SignatureRequestRead, tags=["signature requests - command"])
async def cancel_request(request_id: str, context: AuthContext = Depends(require_permission("signature_requests:write"))) -> SignatureRequestRead:
    return workflow_service.cancel_request(request_id, context.subject)


@router.get("/signature-requests/{request_id}/audit", response_model=list[AuditEventRead], tags=["audit - query"])
async def request_audit(request_id: str, _context: AuthContext = Depends(require_permission("audit:read"))) -> list[AuditEventRead]:
    return workflow_service.audit_events(request_id)


@router.get("/signing/links/{token}", response_model=SigningRead, tags=["signing - query"])
async def signing_context(token: str, context: AuthContext = Depends(authenticated_context)) -> SigningRead:
    return workflow_service.signing_context(token, context.subject)

@router.get("/signing/links/{token}/document", tags=["signing - query"])
async def signing_document(token: str, context: AuthContext = Depends(authenticated_context)) -> Response:
    metadata, content = workflow_service.signing_document(token, context.subject)
    return Response(content, media_type=metadata.content_type, headers={"Content-Disposition": f'inline; filename="{metadata.original_filename}"', "X-Document-SHA256": metadata.sha256})


@router.get("/signing/links/{token}/download", tags=["signing - query"])
async def download_signing_document(token: str, context: AuthContext = Depends(authenticated_context)) -> Response:
    metadata, content = workflow_service.signing_document(token, context.subject)
    return Response(content, media_type=metadata.content_type, headers={"Content-Disposition": f'attachment; filename="{metadata.original_filename}"', "X-Document-SHA256": metadata.sha256})


@router.get("/signing/links/{token}/signed-document", tags=["signing - query"])
async def signing_signed_document(token: str, context: AuthContext = Depends(authenticated_context)) -> Response:
    filename, digest, content = workflow_service.signing_signed_document(token, context.subject)
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"', "X-Signed-Document-SHA256": digest})


@router.post("/signing/links/{token}/view", response_model=SignerRead, tags=["signing - command"])
async def view_document(token: str, context: AuthContext = Depends(authenticated_context)) -> SignerRead:
    return workflow_service.view(token, context.subject)


@router.post("/signing/links/{token}/sign", response_model=SignerRead, tags=["signing - command"])
async def sign_document(token: str, payload: SignCommand, request: Request, context: AuthContext = Depends(authenticated_context)) -> SignerRead:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip_address = forwarded.split(",")[-1].strip() if forwarded else (request.client.host if request.client else "unknown")
    return workflow_service.sign(token, context.subject, payload.consent, payload.stamp, consent_version=payload.consent_version, client=payload.client, geolocation=payload.geolocation, ip_address=ip_address, user_agent=request.headers.get("user-agent", "unknown"))


@router.post("/signing/links/{token}/decline", response_model=SignerRead, tags=["signing - command"])
async def decline_document(token: str, context: AuthContext = Depends(authenticated_context)) -> SignerRead:
    return workflow_service.decline(token, context.subject)
