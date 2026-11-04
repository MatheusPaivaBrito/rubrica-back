from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy import case, func

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseDocument, EnterpriseRequest, EnterpriseSignature
from core_api.modules.enterprise.machine_context import MachineContext
from core_api.modules.enterprise.router import recovery_binding as binding
from core_api.modules.enterprise.storage_entities import CopyRemoval, MigrationDocument, MigrationItem, StorageMigration, StoragePolicy
from core_api.modules.enterprise.storage_migration import prepare_document, source_stream
from core_api.modules.enterprise.storage_router import destination_for, router
from core_api.modules.enterprise.usage import record_usage
from core_api.modules.tenant.tenant_service import tenant_service


class MigrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination_id: UUID
    acknowledge_plaintext_export: bool
    include_existing: bool = True
    apply_to_new_uploads: bool = False


def lookup_job(db, tenant_id, integration_id, migration_id, context):
    integration = binding(db, tenant_id, integration_id, context)
    job = db.scalar(select(StorageMigration).where(StorageMigration.id == migration_id,
        StorageMigration.tenant_id == tenant_id, StorageMigration.integration_id == integration_id).with_for_update())
    if job is None:
        raise HTTPException(404, "Migration not found")
    return job, destination_for(db, tenant_id, job.destination_id, integration.sandbox)


@router.post("/integrations/{integration_id}/migrations", status_code=201)
def start_migration(tenant_id: UUID, integration_id: UUID, payload: MigrationCreate,
                    context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal.begin() as db:
        integration = binding(db, tenant_id, integration_id, context)
        destination = destination_for(db, tenant_id, payload.destination_id, integration.sandbox)
        if not payload.include_existing and not payload.apply_to_new_uploads:
            raise HTTPException(422, "Select existing documents or a policy for future uploads")
        if destination.kind != "rubrica" and not payload.acknowledge_plaintext_export:
            raise HTTPException(422, "Confirm responsibility for encryption and access at the destination")
        if destination.validated_at is None:
            raise HTTPException(409, "Validate the destination first")
        pending = db.scalar(select(StorageMigration.id).where(StorageMigration.integration_id == integration_id,
            StorageMigration.status == "pending").limit(1))
        if pending and payload.include_existing:
            raise HTTPException(409, "A migration is already pending for this integration")
        job = StorageMigration(tenant_id=tenant_id, integration_id=integration_id,
            destination_id=destination.id, created_by=context.subject,
            export_acknowledged_at=datetime.now(UTC) if payload.acknowledge_plaintext_export else None)
        db.add(job)
        db.flush()
        if payload.apply_to_new_uploads:
            policy = db.scalar(select(StoragePolicy).where(StoragePolicy.integration_id == integration_id))
            if policy is None:
                db.add(StoragePolicy(integration_id=integration_id, destination_id=destination.id, updated_by=context.subject))
            else:
                policy.destination_id, policy.updated_by = destination.id, context.subject
        # Snapshot of existing documents; later uploads are intentionally not
        # silently included in an administrator's acknowledged export.
        documents = db.scalars(select(EnterpriseDocument.id).join(EnterpriseCompartment,
            EnterpriseCompartment.id == EnterpriseDocument.compartment_id).where(
            EnterpriseCompartment.integration_id == integration_id, EnterpriseDocument.deleted_at.is_(None)))
        if payload.include_existing:
            for document_id in documents:
                db.add(MigrationDocument(migration_id=job.id, document_id=document_id))
        tenant_service._audit(db, tenant_id, context.subject, "enterprise.storage.migration.started",
                              {"migration_id": str(job.id), "destination_id": str(destination.id)})
        return {"id": job.id, "status": job.status, "source_preserved": True}


@router.get("/integrations/{integration_id}/migrations")
def list_migrations(tenant_id: UUID, integration_id: UUID,
                    context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        binding(db, tenant_id, integration_id, context)
        return [{"id": job.id, "status": job.status, "created_at": job.created_at} for job in db.scalars(
            select(StorageMigration).where(StorageMigration.integration_id == integration_id,
                StorageMigration.tenant_id == tenant_id).order_by(case((StorageMigration.status == "pending", 0), else_=1),
                    StorageMigration.created_at.desc(), StorageMigration.id.desc()).limit(20))]


@router.get("/integrations/{integration_id}/migrations/{migration_id}")
def migration_progress(tenant_id: UUID, integration_id: UUID, migration_id: UUID,
                       context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        job, destination = lookup_job(db, tenant_id, integration_id, migration_id, context)
        documents = [{"document_id": entry.document_id, "status": entry.status,
                      "rubrica_copy_removed": db.get(EnterpriseDocument, entry.document_id).rubrica_copy_deleted_at is not None} for entry in db.scalars(
            select(MigrationDocument).where(MigrationDocument.migration_id == job.id))]
        items = [{"id": item.id, "document_id": item.document_id, "kind": item.source_kind,
                  "sha256": item.sha256, "size_bytes": item.size_bytes, "status": item.status,
                  "attempts": item.attempts, "error_code": item.error_code, "verified_at": item.verified_at}
                 for item in db.scalars(select(MigrationItem).where(MigrationItem.migration_id == job.id))]
        removals = [{"id": removal.id, "document_id": removal.document_id, "kind": removal.source_kind,
                     "status": removal.status, "attempts": removal.attempts, "error_code": removal.error_code}
                    for removal in db.scalars(select(CopyRemoval).join(MigrationItem,
                        MigrationItem.id == CopyRemoval.migration_item_id).where(MigrationItem.migration_id == job.id))]
        removed_artifacts = db.scalar(select(func.count()).select_from(EnterpriseSignature).join(EnterpriseRequest,
            EnterpriseRequest.id == EnterpriseSignature.request_id).where(
                EnterpriseRequest.document_id.in_([entry["document_id"] for entry in documents]),
                EnterpriseSignature.rubrica_copy_deleted_at.is_not(None)))
        return {"id": job.id, "status": job.status, "destination_kind": destination.kind,
                "documents": documents, "items": items, "removals": removals,
                "verified_count": sum(item["status"] == "verified" for item in items),
                "total_count": len(items), "source_preserved": not removed_artifacts and not any(entry["rubrica_copy_removed"] for entry in documents)}


def independent_item(db, tenant_id, integration_id, migration_id, item_id, context):
    job, destination = lookup_job(db, tenant_id, integration_id, migration_id, context)
    if destination.kind != "independent":
        raise HTTPException(409, "This migration does not use independent delivery")
    item = db.scalar(select(MigrationItem).where(MigrationItem.id == item_id,
        MigrationItem.migration_id == job.id).with_for_update())
    if item is None:
        raise HTTPException(404, "Migration item not found")
    entry = db.scalar(select(MigrationDocument).where(MigrationDocument.migration_id == job.id,
        MigrationDocument.document_id == item.document_id))
    if not prepare_document(db, job, entry):
        raise HTTPException(409, "Document must be cleared and all signature requests terminal")
    return item, destination


@router.get("/integrations/{integration_id}/migrations/{migration_id}/items/{item_id}/download")
def independent_download(tenant_id: UUID, integration_id: UUID, migration_id: UUID, item_id: UUID,
                         context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal.begin() as db:
        item, destination = independent_item(db, tenant_id, integration_id, migration_id, item_id, context)
        stream = source_stream(db, item, destination.sandbox)
        digest, size, kind = item.sha256, item.size_bytes, item.source_kind

    def chunks():
        completed = False
        try:
            while chunk := stream.read(256 * 1024):
                yield chunk
            completed = True
        finally:
            stream.close()
            if completed:
                with SessionLocal.begin() as db:
                    # Reauthorize after delivery; a revoked membership cannot
                    # confirm a receipt with a stale in-flight response.
                    binding(db, tenant_id, integration_id, context)
                    item = db.get(MigrationItem, item_id)
                    item.downloaded_at = datetime.now(UTC)
    return StreamingResponse(chunks(), media_type="application/json" if kind == "evidence" else "application/pdf",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                 "Content-Length": str(size), "X-Document-SHA256": digest,
                 "Content-Disposition": f'attachment; filename="{item_id}.{"json" if kind == "evidence" else "pdf"}"'})


class DeliveryAcknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    durable_storage_confirmed: bool


@router.post("/integrations/{integration_id}/migrations/{migration_id}/items/{item_id}/acknowledge")
def acknowledge_delivery(tenant_id: UUID, integration_id: UUID, migration_id: UUID, item_id: UUID,
                          payload: DeliveryAcknowledgement,
                          context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal.begin() as db:
        item, destination = independent_item(db, tenant_id, integration_id, migration_id, item_id, context)
        if (item.downloaded_at is None or not payload.durable_storage_confirmed
                or (payload.sha256, payload.size_bytes) != (item.sha256, item.size_bytes)):
            raise HTTPException(409, "Complete the download and confirm durable storage with its hash and size")
        item.status, item.verified_at, item.error_code = "verified", datetime.now(UTC), None
        document = db.get(EnterpriseDocument, item.document_id)
        record_usage(db, MachineContext(tenant_id, integration_id, document.compartment_id,
            "storage-migration", destination.sandbox), "storage.exported", item.id, bytes_count=item.size_bytes)
        tenant_service._audit(db, tenant_id, context.subject, "enterprise.storage.delivery.acknowledged",
                              {"migration_id": str(migration_id), "item_id": str(item.id)})
        return {"id": item.id, "status": item.status, "source_preserved": True}


class RemovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[UUID] = Field(min_length=1, max_length=25)
    confirm_remove_rubrica_copies: bool
    acknowledge_independent_unavailability: bool = False


@router.post("/integrations/{integration_id}/migrations/{migration_id}/remove-copies", status_code=202)
def request_copy_removal(tenant_id: UUID, integration_id: UUID, migration_id: UUID, payload: RemovalRequest,
                          context: AuthContext = Depends(require_permission("documents:write"))):
    from core_api.modules.enterprise.storage_removal import schedule_removal
    with SessionLocal.begin() as db:
        job, destination = lookup_job(db, tenant_id, integration_id, migration_id, context)
        if not payload.confirm_remove_rubrica_copies:
            raise HTTPException(422, "Confirm removal of Rubrica copies")
        if destination.kind == "independent" and not payload.acknowledge_independent_unavailability:
            raise HTTPException(422, "Independent files will no longer be available for download in Rubrica")
        count = schedule_removal(db, job, destination, payload.document_ids, context.subject)
        return {"scheduled_copies": count, "status": "scheduled", "metadata_preserved": True}


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[UUID] = Field(min_length=1, max_length=10)


@router.post("/integrations/{integration_id}/migrations/{migration_id}/restore-copies")
def restore_copies(tenant_id: UUID, integration_id: UUID, migration_id: UUID, payload: RestoreRequest,
                    context: AuthContext = Depends(require_permission("documents:write"))):
    from core_api.modules.enterprise.storage_removal import restore_document
    created_copies = []
    try:
        with SessionLocal.begin() as db:
            from core_api.modules.enterprise.lifecycle import lock_operational
            lock_operational(db, tenant_id)
            job, destination = lookup_job(db, tenant_id, integration_id, migration_id, context)
            count = sum(restore_document(db, job, destination, document_id, context.subject, created_copies)
                        for document_id in sorted(set(payload.document_ids), key=str))
            return {"restored_copies": count, "storage_billing_resumed": count > 0}
    except Exception:
        for storage, key in created_copies:
            try:
                storage.discard_uncommitted(key)
            except Exception:
                pass  # Never turn failed cleanup into a committed reference/counter.
        raise
