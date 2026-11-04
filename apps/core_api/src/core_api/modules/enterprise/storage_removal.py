"""Explicit, durable removal of Rubrica copies after verified export."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.entities import EnterpriseDocument, EnterpriseIntegration, EnterpriseSignature
from core_api.modules.enterprise.machine_context import MachineContext
from core_api.modules.enterprise.storage_access import copy_attributes, external_content
from core_api.modules.enterprise.storage_entities import CopyRemoval, MigrationDocument, MigrationItem, StorageDestination, StorageMigration
from core_api.modules.enterprise.storage_migration import prepare_document
from core_api.modules.enterprise.storage_router import adapter_for
from core_api.modules.enterprise.storage_settings import for_mode
from core_api.modules.enterprise.usage import quota_row, record_usage, reserve_storage
from core_api.modules.tenant.tenant_service import tenant_service


def source_record(db, item):
    if item.source_kind == "original":
        return db.get(EnterpriseDocument, item.source_id)
    if item.source_kind == "artifact":
        return db.get(EnterpriseSignature, item.source_id)
    raise HTTPException(409, "Only document binaries may be removed")


def removal_context(db, job, destination, document):
    integration = db.get(EnterpriseIntegration, job.integration_id)
    if (not integration or integration.environment != settings.ENVIRONMENT or integration.tenant_id != job.tenant_id
            or destination.tenant_id != job.tenant_id or destination.sandbox != integration.sandbox
            or destination.kind not in {"s3", "independent"} or destination.deleted_at is not None):
        raise HTTPException(409, "Invalid removal binding")
    from core_api.modules.enterprise.entities import EnterpriseCompartment
    compartment = db.get(EnterpriseCompartment, document.compartment_id)
    if not compartment or compartment.integration_id != job.integration_id:
        raise HTTPException(409, "Invalid document binding")
    return MachineContext(job.tenant_id, job.integration_id, document.compartment_id, "storage-removal", destination.sandbox)


def verified_manifest(db, job, document_id):
    entry = db.scalar(select(MigrationDocument).where(MigrationDocument.migration_id == job.id,
        MigrationDocument.document_id == document_id))
    if entry is None:
        raise HTTPException(404, "Document is not part of this migration")
    items = prepare_document(db, job, entry)
    if not items or any(item.status != "verified" or item.verified_at is None for item in items):
        raise HTTPException(409, "All signature requests must be terminal and the complete manifest verified")
    entry.status = "verified"
    return items


def schedule_removal(db, job, destination, document_ids, subject):
    if job.status != "completed":
        raise HTTPException(409, "Complete the migration before requesting source removal")
    count = 0
    for document_id in sorted(set(document_ids), key=str):
        items = verified_manifest(db, job, document_id)
        document = db.get(EnterpriseDocument, document_id)
        removal_context(db, job, destination, document)
        for item in items:
            if destination.kind == "independent" and item.downloaded_at is None:
                raise HTTPException(409, "Independent delivery must be acknowledged first")
            if item.source_kind == "evidence":
                continue  # Evidence/audit metadata remain subject to their retention policy.
            record = source_record(db, item)
            key, _, _ = copy_attributes(record, item.source_kind)
            existing = db.scalar(select(CopyRemoval).where(CopyRemoval.source_kind == item.source_kind,
                CopyRemoval.source_id == item.source_id, CopyRemoval.storage_key == key))
            if existing is not None:
                if existing.status in {"pending", "retry"} and existing.migration_item_id != item.id:
                    # Explicit administrator action can replace an unusable
                    # receipt after credential rotation, retaining intent ID.
                    existing.migration_item_id, existing.requested_by = item.id, subject
                    existing.next_attempt_at, existing.error_code = datetime.now(UTC), None
                    count += 1
                continue
            if record.rubrica_copy_deleted_at is not None:
                continue
            db.add(CopyRemoval(migration_item_id=item.id, document_id=document_id, source_kind=item.source_kind,
                source_id=item.source_id, storage_key=key, requested_by=subject, next_attempt_at=datetime.now(UTC)))
            count += 1
    tenant_service._audit(db, job.tenant_id, subject, "enterprise.storage.removal.requested",
                          {"migration_id": str(job.id), "copies": count})
    return count


def process_removal(db, removal):
    receipt = db.get(MigrationItem, removal.migration_item_id)
    job = db.get(StorageMigration, receipt.migration_id)
    destination = db.get(StorageDestination, job.destination_id)
    document = db.get(EnterpriseDocument, removal.document_id)
    context = removal_context(db, job, destination, document)
    verified_manifest(db, job, document.id)
    record = source_record(db, receipt)
    key, digest, size = copy_attributes(record, receipt.source_kind)
    if (receipt.source_kind, receipt.source_id, receipt.document_id) != (removal.source_kind, removal.source_id, document.id):
        raise HTTPException(409, "Removal receipt binding mismatch")
    if key != removal.storage_key:
        removal.status, removal.error_code = "superseded", "copy_generation_changed"
        return
    if (receipt.sha256, receipt.size_bytes) != (digest, size):
        raise HTTPException(409, "Removal receipt integrity mismatch")
    if destination.kind == "s3":
        if not receipt.target_key:
            raise HTTPException(409, "External receipt is incomplete")
        with adapter_for(destination).read_verified(receipt.target_key, digest, size):
            pass  # Reconfirm destination immediately before destructive action.
    elif receipt.downloaded_at is None or job.export_acknowledged_at is None:
        raise HTTPException(409, "Independent delivery was not acknowledged")
    if record.rubrica_copy_deleted_at is not None:
        removal.status, removal.completed_at = "deleted", record.rubrica_copy_deleted_at
        return
    quota = quota_row(db, context)
    if quota.storage_bytes < size or (receipt.source_kind == "original" and quota.document_count < 1):
        raise HTTPException(409, "Storage meter requires reconciliation")
    storage = configured_document_storage(for_mode(settings, context.sandbox, record.storage_namespace))
    storage.remove_copy(key)  # Strict and idempotent; 403/bucket lock never means deleted.
    now = datetime.now(UTC)
    quota.storage_bytes -= size
    if receipt.source_kind == "original":
        quota.document_count -= 1
    record.rubrica_copy_deleted_at = now
    removal.status, removal.completed_at, removal.error_code = "deleted", now, None
    record_usage(db, context, "storage.removed", removal.id, bytes_count=size, now=now)
    tenant_service._audit(db, job.tenant_id, removal.requested_by, "enterprise.storage.copy.removed",
                          {"removal_id": str(removal.id), "document_id": str(document.id), "size_bytes": size})


def remove_once():
    with SessionLocal.begin() as db:
        now = datetime.now(UTC)
        candidate = db.execute(select(CopyRemoval.id, CopyRemoval.document_id).join(MigrationItem, MigrationItem.id == CopyRemoval.migration_item_id)
            .join(StorageMigration, StorageMigration.id == MigrationItem.migration_id)
            .join(EnterpriseIntegration, EnterpriseIntegration.id == StorageMigration.integration_id).where(
                CopyRemoval.status.in_(["pending", "retry"]), CopyRemoval.next_attempt_at <= now,
                EnterpriseIntegration.environment == settings.ENVIRONMENT,
            ).order_by(CopyRemoval.next_attempt_at, CopyRemoval.id).limit(1)).first()
        if candidate is None:
            return False
        from core_api.modules.billing.billing_entity import BillingAccountEntity
        from core_api.modules.enterprise.lifecycle import contract_view, lifecycle_for
        receipt = db.get(MigrationItem, db.get(CopyRemoval, candidate.id).migration_item_id)
        job = db.get(StorageMigration, receipt.migration_id)
        account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == job.tenant_id).with_for_update())
        if contract_view(account, lifecycle_for(db, job.tenant_id))["status"] in {"expired", "purging", "purged"}:
            db.get(CopyRemoval, candidate.id).status = "superseded"
            return True
        # Compartment precedes intent locks, including administrator receipt
        # replacement; never wait for a compartment while holding its intent.
        from core_api.modules.enterprise.entities import EnterpriseCompartment
        document = db.get(EnterpriseDocument, candidate.document_id)
        compartment = db.scalar(select(EnterpriseCompartment.id).where(EnterpriseCompartment.id == document.compartment_id)
            .with_for_update(skip_locked=True))
        if compartment is None:
            return False
        removal = db.scalar(select(CopyRemoval).where(CopyRemoval.id == candidate.id,
            CopyRemoval.status.in_(["pending", "retry"]), CopyRemoval.next_attempt_at <= now)
            .with_for_update(skip_locked=True).execution_options(populate_existing=True))
        if removal is None:
            return False
        removal.attempts += 1
        try:
            with db.begin_nested():
                process_removal(db, removal)
        except Exception:
            removal.status, removal.error_code = "retry", "removal_not_confirmed"
            removal.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(removal.attempts, 8)))
        return True


def restore_document(db, job, destination, document_id, subject, created_copies):
    from core_api.modules.enterprise.document_access import verified_content
    document = db.get(EnterpriseDocument, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    context = removal_context(db, job, destination, document)
    items = verified_manifest(db, job, document_id)
    pending = db.scalar(select(CopyRemoval.id).where(CopyRemoval.document_id == document_id,
        CopyRemoval.status.in_(["pending", "retry"])).limit(1))
    if pending:
        raise HTTPException(409, "Wait for pending removal operations before restoring")
    storage = configured_document_storage(for_mode(settings, context.sandbox))
    count = 0
    for item in items:
        if item.source_kind == "evidence":
            continue
        record = source_record(db, item)
        if record.rubrica_copy_deleted_at is None:
            continue
        old_key, digest, size = copy_attributes(record, item.source_kind)
        reserve_storage(db, context, size, document=item.source_kind == "original")
        with external_content(db, context, item.source_kind, record) as source:
            scope = f"tenants/{context.tenant_id}/enterprise/{'sandbox' if context.sandbox else 'live'}/{context.integration_id}/{context.compartment_id}/{document.id}"
            key, actual_size = storage.put(source, filename="restored.pdf", sha256=digest, scope=scope)
        created_copies.append((storage, key))
        if actual_size != size:
            raise HTTPException(409, "Restored document size mismatch")
        with verified_content(storage, key, digest, size):
            pass
        if item.source_kind == "original":
            record.storage_key = key
        else:
            record.artifact_storage_key = key
        record.storage_namespace, record.rubrica_copy_deleted_at = "isolated-v1", None
        for intent in db.scalars(select(CopyRemoval).where(CopyRemoval.source_kind == item.source_kind,
            CopyRemoval.source_id == item.source_id, CopyRemoval.storage_key == old_key, CopyRemoval.status == "deleted")):
            intent.status = "restored"
        record_usage(db, context, "storage.added", uuid4(), bytes_count=size)
        count += 1
    tenant_service._audit(db, job.tenant_id, subject, "enterprise.storage.copies.restored",
                          {"document_id": str(document_id), "copies": count})
    return count
