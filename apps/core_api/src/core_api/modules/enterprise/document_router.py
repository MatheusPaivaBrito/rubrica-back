from hashlib import sha256
from io import BytesIO
from threading import BoundedSemaphore
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.pdf_validation import validate_pdf_upload
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseDocument, EnterpriseIntegration
from core_api.modules.enterprise.storage_policy import enroll_document
from core_api.modules.enterprise.machine_context import MachineContext, require_machine
from core_api.modules.tenant.tenant_service import tenant_service
from core_api.modules.enterprise.storage_settings import for_mode
from core_api.modules.enterprise.usage import record_usage, reserve_storage

router = APIRouter(tags=["enterprise documents"])
MAX_PDF_BYTES = 50_000_000
_UPLOAD_SLOTS = BoundedSemaphore(settings.ENTERPRISE_UPLOAD_CONCURRENCY)
_SANDBOX_UPLOAD_SLOTS = BoundedSemaphore(1)


def upload_slots(sandbox):
    return _SANDBOX_UPLOAD_SLOTS if sandbox else _UPLOAD_SLOTS


async def read_pdf_body(request: Request) -> bytes:
    size = request.headers.get("content-length")
    if size is not None:
        try:
            declared = int(size)
        except ValueError as exc:
            raise HTTPException(400, "Invalid Content-Length") from exc
        if declared < 0:
            raise HTTPException(400, "Invalid Content-Length")
        if declared > MAX_PDF_BYTES:
            raise HTTPException(413, "PDF exceeds 50 MB")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_PDF_BYTES:
            raise HTTPException(413, "PDF exceeds 50 MB")
        body.extend(chunk)
    return bytes(body)


def persist_upload(context, content, filename, content_type, idempotency_key):
    validate_pdf_upload(content, filename=filename, content_type=content_type, deep=False)
    digest = sha256(content).hexdigest()
    storage = configured_document_storage(for_mode(settings, context.sandbox))
    storage_key = None
    try:
        with SessionLocal.begin() as db:
            from core_api.modules.enterprise.lifecycle import lock_operational
            lock_operational(db, context.tenant_id)
            db.scalar(select(EnterpriseIntegration).where(EnterpriseIntegration.id == context.integration_id).with_for_update())
            # Serialize same-compartment uploads, including competing retries.
            compartment = db.scalar(select(EnterpriseCompartment).where(
                EnterpriseCompartment.id == context.compartment_id,
                EnterpriseCompartment.integration_id == context.integration_id,
                EnterpriseCompartment.deleted_at.is_(None),
            ).with_for_update())
            if compartment is None:
                raise HTTPException(404, "Compartment not found")
            item = db.scalar(select(EnterpriseDocument).where(
                EnterpriseDocument.compartment_id == context.compartment_id,
                EnterpriseDocument.idempotency_key == idempotency_key,
            ))
            if item is not None:
                if item.sha256 != digest or item.filename != filename or item.deleted_at is not None:
                    raise HTTPException(409, "Idempotency key already used with different content")
                return {"id": item.id, "sha256": item.sha256, "size_bytes": item.size_bytes, "status": item.status}
            document_id = uuid4()
            mode = "sandbox" if context.sandbox else "live"
            scope = f"tenants/{context.tenant_id}/enterprise/{mode}/{context.integration_id}/{context.compartment_id}/{document_id}"
            reserve_storage(db, context, len(content), document=True)
            storage_key, size = storage.put(BytesIO(content), filename=filename, sha256=digest, scope=scope)
            item = EnterpriseDocument(id=document_id, compartment_id=context.compartment_id,
                filename=filename, sha256=digest, size_bytes=size, storage_key=storage_key,
                idempotency_key=idempotency_key, token_public_id=context.token_public_id)
            db.add(item)
            db.flush()
            enroll_document(db, context, item.id)
            record_usage(db, context, "document.uploaded", item.id, bytes_count=size)
            tenant_service._audit(db, context.tenant_id,
                f"integration:{context.integration_id}", "enterprise.document.uploaded",
                {"document_id": str(item.id), "compartment_id": str(context.compartment_id),
                 "token_public_id": context.token_public_id, "sandbox": context.sandbox,
                 "size_bytes": size, "status": item.status})
            return {"id": item.id, "sha256": item.sha256, "size_bytes": item.size_bytes, "status": item.status}
    except Exception:
        if storage_key:
            storage.discard_uncommitted(storage_key)
        raise


@router.post("/api/v1/compartments/{compartment_id}/documents", status_code=201)
@router.post("/api/v1/sandbox/compartments/{compartment_id}/documents", status_code=201)
async def upload(
    compartment_id: UUID, request: Request,
    filename: str = Query(min_length=1, max_length=120),
    idempotency_key: str = Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    context: MachineContext = Depends(require_machine("documents:create")),
):
    content_type = request.headers.get("content-type", "")
    if content_type.split(";", 1)[0].strip().lower() != "application/pdf":
        raise HTTPException(415, "Only PDF documents are accepted")
    slots = upload_slots(context.sandbox)
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Upload capacity temporarily exhausted", headers={"Retry-After": "5"})
    try:
        content = await read_pdf_body(request)
        return await run_in_threadpool(persist_upload, context, content, filename,
                                     content_type, idempotency_key)
    finally:
        slots.release()
