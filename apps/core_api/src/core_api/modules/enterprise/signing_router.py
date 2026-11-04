from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.document_access import lookup_document, require_available
from core_api.modules.enterprise.entities import EnterpriseSignature
from core_api.modules.enterprise.machine_context import MachineContext, require_machine
from core_api.modules.enterprise.request_router import lookup_request
from core_api.modules.enterprise.signing_service import resolve_session
from core_api.modules.enterprise.storage_access import open_copy
from core_api.modules.enterprise.streaming import measured_chunks
from core_api.modules.enterprise.usage import reserve_api_request
from core_api.modules.signature_request.workflow_schema import StampPosition
from fastapi.responses import StreamingResponse
from core_api.infrastructure.content_disposition import pdf_content_disposition

router = APIRouter(tags=["enterprise signer sessions"])


def session_secret(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer ") or len(authorization) != 50:
        raise HTTPException(401, "Restricted signing session required")
    return authorization[7:]


def is_sandbox(request):
    return request.url.path.startswith("/api/v1/sandbox/")


def count_session_request(request, context):
    request.state.machine_context = context
    with SessionLocal.begin() as db:
        reserve_api_request(db, context)


class ConsentCommand(BaseModel):
    consent: bool
    consent_version: str = Field(max_length=80)
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stamp: StampPosition | None = None
    drawn_signature_png_data_url: str | None = Field(default=None, max_length=400_000)

    @field_validator("drawn_signature_png_data_url")
    @classmethod
    def normalize_drawing(cls, value):
        from core_api.modules.signature_request.workflow_schema import _normalized_png_data_url
        return _normalized_png_data_url(value)


def pdf_response(stream, filename, digest, size, context):
    return StreamingResponse(measured_chunks(stream, context, size), media_type="application/pdf", headers={
        "Cache-Control": "private, no-store", "Content-Disposition": pdf_content_disposition(filename, attachment=True),
        "X-Content-Type-Options": "nosniff", "X-Document-SHA256": digest, "Content-Length": str(size),
    })


@router.get("/api/v1/signing-session")
@router.get("/api/v1/sandbox/signing-session")
def session_context(request: Request, response: Response, secret: str = Depends(session_secret)):
    response.headers["Cache-Control"] = "no-store"
    with SessionLocal() as db:
        context, item, signer, session = resolve_session(db, secret, is_sandbox(request))
        count_session_request(request, context)
        return {"request_id": item.id, "document_id": item.document_id, "document_sha256": item.document_sha256,
                "signer": signer, "expires_at": session.expires_at,
                "consent_version": "rubrica-enterprise-evidence-v1", "sandbox": context.sandbox,
                "identity_source": "integrator_declared", "consumed": session.used_at is not None}


@router.get("/api/v1/signing-session/document")
@router.get("/api/v1/sandbox/signing-session/document")
def session_document(request: Request, secret: str = Depends(session_secret)):
    with SessionLocal() as db:
        context, item, _, _ = resolve_session(db, secret, is_sandbox(request))
        count_session_request(request, context)
        document = lookup_document(db, context, item.document_id)
        require_available(document)
        stream = open_copy(db, context, "original", document, storage_factory=configured_document_storage)
        return pdf_response(stream, document.filename, item.document_sha256, document.size_bytes, context)


@router.post("/api/v1/signing-session/consent", status_code=202)
@router.post("/api/v1/sandbox/signing-session/consent", status_code=202)
def consent(request: Request, payload: ConsentCommand, response: Response, secret: str = Depends(session_secret)):
    response.headers["Cache-Control"] = "no-store"
    with SessionLocal() as db:
        context, _, _, _ = resolve_session(db, secret, is_sandbox(request))
    count_session_request(request, context)
    if not payload.consent or payload.consent_version != "rubrica-enterprise-evidence-v1":
        raise HTTPException(422, "Explicit supported signer consent is required")
    from core_api.modules.enterprise.jobs import enqueue
    from core_api.modules.enterprise.provider_operations import command_hash
    return enqueue(context, "sign", {"session_secret": secret, "command": payload.model_dump(mode="json"),
        "ip_address": request.client.host if request.client else "unknown", "user_agent": request.headers.get("user-agent", "unknown")[:1000]},
        f"{secret}:{command_hash(payload)}")


@router.post("/api/v1/signing-session/serproid/start")
def serproid_start(request: Request, payload: ConsentCommand, response: Response, secret: str = Depends(session_secret)):
    from core_api.modules.enterprise.serproid_authorization import start
    response.headers["Cache-Control"] = "no-store"
    with SessionLocal() as db:
        context, _, _, _ = resolve_session(db, secret, False)
    count_session_request(request, context)
    return start(secret, False, payload, ip_address=request.client.host if request.client else "unknown",
                 user_agent=request.headers.get("user-agent", "unknown"))


@router.get("/api/v1/serproid/callback", include_in_schema=False)
def serproid_callback(response: Response, state: str = Query(min_length=43, max_length=43),
                     code: str | None = Query(default=None, max_length=4096),
                     error: str | None = Query(default=None, max_length=256)):
    from core_api.modules.enterprise.serproid_authorization import consume_attempt
    from core_api.modules.enterprise.jobs import enqueue
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    tenant_id, attempt = consume_attempt(state)
    if error or not code:
        return {"status": "authorization_denied"}
    with SessionLocal() as db:
        context, _, _, _ = resolve_session(db, attempt["session_secret"], False)
    if context.tenant_id != tenant_id:
        raise HTTPException(403, "Provider authorization context mismatch")
    response.status_code = 202
    return enqueue(context, "serpro_callback", {"attempt": attempt, "code": code, "tenant_id": str(tenant_id)}, state)


@router.get("/api/v1/signing-session/jobs/{job_id}")
@router.get("/api/v1/sandbox/signing-session/jobs/{job_id}")
def signer_job(job_id: UUID, request: Request, secret: str = Depends(session_secret)):
    from core_api.modules.enterprise.jobs import scoped_job, job_read
    with SessionLocal() as db:
        context, _, _, session = resolve_session(db, secret, is_sandbox(request))
        item = scoped_job(db, context, job_id)
        if item.signing_session_id != session.id:
            raise HTTPException(404, "Processing job not found")
        return job_read(item)


@router.post("/api/v1/signing-session/jobs/{job_id}/retry", status_code=202)
@router.post("/api/v1/sandbox/signing-session/jobs/{job_id}/retry", status_code=202)
def retry_signer_job(job_id: UUID, request: Request, secret: str = Depends(session_secret)):
    from core_api.modules.enterprise.jobs import scoped_job, job_read
    from core_api.modules.enterprise.lifecycle import lock_operational
    with SessionLocal.begin() as db:
        context, _, _, session = resolve_session(db, secret, is_sandbox(request), lock=True)
        lock_operational(db, context.tenant_id)
        item = scoped_job(db, context, job_id)
        if item.signing_session_id != session.id or item.kind != "sign":
            raise HTTPException(404, "Retriable signer job not found")
        if item.status not in {"failed", "uncertain"} or not item.encrypted_payload:
            raise HTTPException(409, "Only retained failed/uncertain signer jobs can be retried")
        item.status, item.error_code = "queued", None
        return job_read(item)


@router.get("/api/v1/compartments/{compartment_id}/signature-requests/{request_id}/artifact")
@router.get("/api/v1/sandbox/compartments/{compartment_id}/signature-requests/{request_id}/artifact")
def artifact(request_id: UUID, context: MachineContext = Depends(require_machine("documents:download"))):
    with SessionLocal() as db:
        item = lookup_request(db, context, request_id)
        latest = db.scalar(select(EnterpriseSignature).where(
            EnterpriseSignature.request_id == item.id, EnterpriseSignature.deleted_at.is_(None),
        ).order_by(EnterpriseSignature.signed_at.desc(), EnterpriseSignature.id.desc()).limit(1))
        if latest is None:
            raise HTTPException(404, "Signed artifact not found")
        stream = open_copy(db, context, "artifact", latest, storage_factory=configured_document_storage)
        return pdf_response(stream, f"rubrica-{item.id}-signed.pdf", latest.artifact_sha256, latest.artifact_size, context)
