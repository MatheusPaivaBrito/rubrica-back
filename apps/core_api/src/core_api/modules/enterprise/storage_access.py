"""Authenticated reads use only receipts scoped to the authorized document."""
from fastapi import HTTPException
from sqlalchemy import select

from core_api.infrastructure.settings import settings
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseDocument, EnterpriseIntegration, EnterpriseRequest
from core_api.modules.enterprise.storage_entities import CopyRemoval, MigrationItem, StorageDestination, StorageMigration
from core_api.modules.enterprise.storage_router import adapter_for
from core_api.modules.enterprise.storage_settings import for_mode


def copy_attributes(record, kind):
    if kind == "original":
        return record.storage_key, record.sha256, record.size_bytes
    if kind == "artifact":
        return record.artifact_storage_key, record.artifact_sha256, record.artifact_size
    raise ValueError("Only binary source copies have storage locations")


def document_for(db, context, kind, record):
    request = db.get(EnterpriseRequest, record.request_id) if kind == "artifact" else None
    document = record if kind == "original" else db.get(EnterpriseDocument, request.document_id) if request else None
    if document is None or document.compartment_id != context.compartment_id or document.deleted_at is not None:
        raise HTTPException(404, "Document not found")
    compartment = db.get(EnterpriseCompartment, document.compartment_id)
    integration = db.get(EnterpriseIntegration, compartment.integration_id) if compartment else None
    if (integration is None or integration.id != context.integration_id or integration.tenant_id != context.tenant_id
            or integration.sandbox != context.sandbox or integration.environment != settings.ENVIRONMENT):
        raise HTTPException(404, "Document not found")
    return document


def external_content(db, context, kind, record):
    document = document_for(db, context, kind, record)
    _, digest, size = copy_attributes(record, kind)
    rows = list(db.execute(select(MigrationItem, StorageDestination).join(StorageMigration,
        StorageMigration.id == MigrationItem.migration_id).join(StorageDestination,
        StorageDestination.id == StorageMigration.destination_id).where(
        MigrationItem.source_kind == kind, MigrationItem.source_id == record.id,
        MigrationItem.document_id == document.id,
        MigrationItem.sha256 == digest, MigrationItem.size_bytes == size, MigrationItem.status == "verified",
        StorageMigration.tenant_id == context.tenant_id, StorageMigration.integration_id == context.integration_id,
        StorageDestination.tenant_id == context.tenant_id, StorageDestination.sandbox == context.sandbox,
        StorageDestination.deleted_at.is_(None),
    ).order_by(MigrationItem.verified_at.desc(), MigrationItem.id.desc()).limit(20)))
    for receipt, destination in rows:
        if destination.kind == "s3" and receipt.target_key:
            # Full verification happens before any plaintext is returned.
            try:
                return adapter_for(destination).read_verified(receipt.target_key, digest, size)
            except FileNotFoundError as exc:
                raise HTTPException(502, "Verified external copy is no longer available") from exc
    if any(destination.kind == "independent" for _, destination in rows):
        raise HTTPException(410, "File exported to customer storage; upload a new copy to use it in Rubrica")
    raise HTTPException(409, "No verified external copy is available")


def open_copy(db, context, kind, record, *, storage_factory=None):
    from core_api.modules.enterprise.document_access import verified_content
    document_for(db, context, kind, record)
    key, digest, size = copy_attributes(record, kind)
    if record.rubrica_copy_deleted_at is None:
        storage = (storage_factory or configured_document_storage)(for_mode(settings, context.sandbox, record.storage_namespace))
        try:
            return verified_content(storage, key, digest, size)
        except FileNotFoundError:
            # Handles a worker crash after deletion but before DB confirmation.
            intent = db.scalar(select(CopyRemoval.id).where(CopyRemoval.source_kind == kind,
                CopyRemoval.source_id == record.id, CopyRemoval.storage_key == key).limit(1))
            if intent is None:
                raise
    return external_content(db, context, kind, record)


def ensure_signable_copy(db, document):
    pending = db.scalar(select(CopyRemoval.id).where(CopyRemoval.document_id == document.id,
        CopyRemoval.status.in_(["pending", "retry"])).limit(1))
    if pending or document.rubrica_copy_deleted_at is not None:
        raise HTTPException(409, "Restore the Rubrica copies before starting another signature request")
