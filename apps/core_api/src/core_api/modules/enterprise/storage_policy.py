from datetime import UTC, datetime

from sqlalchemy import select

from core_api.modules.enterprise.storage_entities import MigrationDocument, StorageMigration, StoragePolicy


def enroll_document(db, context, document_id):
    """Caller holds integration then compartment locks. Each operation has a
    durable job, avoiding locks in reverse order with a migrating worker."""
    policy = db.scalar(select(StoragePolicy).where(StoragePolicy.integration_id == context.integration_id))
    if policy is None:
        return
    job = StorageMigration(tenant_id=context.tenant_id, integration_id=context.integration_id,
        destination_id=policy.destination_id, created_by=f"integration:{context.integration_id}",
        export_acknowledged_at=datetime.now(UTC))
    db.add(job)
    db.flush()
    db.add(MigrationDocument(migration_id=job.id, document_id=document_id))
