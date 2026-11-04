"""Document access never returns internal storage keys or bypasses quarantine."""

from hashlib import sha256
from tempfile import SpooledTemporaryFile
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from core_api.infrastructure.content_disposition import pdf_content_disposition
from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.entities import EnterpriseDocument
from core_api.modules.enterprise.machine_context import MachineContext, require_machine
from core_api.modules.enterprise.storage_access import open_copy
from core_api.modules.enterprise.streaming import measured_chunks

router = APIRouter(tags=["enterprise documents"])


def lookup_document(db, context: MachineContext, document_id, *, lock=False):
    statement = select(EnterpriseDocument).where(
        EnterpriseDocument.id == document_id,
        EnterpriseDocument.compartment_id == context.compartment_id,
        EnterpriseDocument.deleted_at.is_(None),
    )
    item = db.scalar(statement.with_for_update() if lock else statement)
    if item is None:
        raise HTTPException(404, "Document not found")
    return item


def metadata(item):
    return {"id": item.id, "filename": item.filename, "sha256": item.sha256,
            "size_bytes": item.size_bytes, "status": item.status, "created_at": item.created_at}


def require_available(item):
    if item.status != "ready":
        raise HTTPException(409, "Document is not cleared for use")


def verified_content(storage, storage_key, digest, expected_size):
    """Verify complete plaintext before returning any download bytes."""
    output = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    try:
        checksum = sha256()
        size = 0
        with storage.get(storage_key) as stream:
            while chunk := stream.read(256 * 1024):
                size += len(chunk)
                if size > expected_size:
                    raise HTTPException(409, "Document integrity check failed")
                checksum.update(chunk)
                output.write(chunk)
        if size != expected_size or checksum.hexdigest() != digest:
            raise HTTPException(409, "Document integrity check failed")
        output.seek(0)
        return output
    except Exception:
        output.close()
        raise


@router.get("/api/v1/compartments/{compartment_id}/documents")
@router.get("/api/v1/sandbox/compartments/{compartment_id}/documents")
def list_documents(
    context: MachineContext = Depends(require_machine("documents:read")),
    limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000),
):
    with SessionLocal() as db:
        rows = db.scalars(select(EnterpriseDocument).where(
            EnterpriseDocument.compartment_id == context.compartment_id,
            EnterpriseDocument.deleted_at.is_(None),
        ).order_by(EnterpriseDocument.created_at.desc(), EnterpriseDocument.id.desc()).offset(offset).limit(limit))
        return [metadata(item) for item in rows]


@router.get("/api/v1/compartments/{compartment_id}/documents/{document_id}")
@router.get("/api/v1/sandbox/compartments/{compartment_id}/documents/{document_id}")
def get_document(document_id: UUID, context: MachineContext = Depends(require_machine("documents:read"))):
    with SessionLocal() as db:
        return metadata(lookup_document(db, context, document_id))


@router.post("/api/v1/compartments/{compartment_id}/documents/{document_id}/scan")
@router.post("/api/v1/sandbox/compartments/{compartment_id}/documents/{document_id}/scan")
def scan(document_id: UUID, context: MachineContext = Depends(require_machine("documents:create"))):
    from core_api.modules.enterprise.scanning import scan_document
    from core_api.modules.enterprise.document_router import upload_slots
    slots = upload_slots(context.sandbox)
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Scanning capacity temporarily exhausted", headers={"Retry-After": "5"})
    try:
        return scan_document(context, document_id)
    finally:
        slots.release()


@router.get("/api/v1/compartments/{compartment_id}/documents/{document_id}/download")
@router.get("/api/v1/sandbox/compartments/{compartment_id}/documents/{document_id}/download")
def download(document_id: UUID, context: MachineContext = Depends(require_machine("documents:download"))):
    with SessionLocal() as db:
        item = lookup_document(db, context, document_id)
        require_available(item)
        digest, size, filename = item.sha256, item.size_bytes, item.filename
        stream = open_copy(db, context, "original", item, storage_factory=configured_document_storage)

    return StreamingResponse(measured_chunks(stream, context, size), media_type="application/pdf", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": pdf_content_disposition(filename, attachment=True),
        "X-Document-SHA256": digest, "Content-Length": str(size),
    })
