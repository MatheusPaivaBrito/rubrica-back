"""Retriable copy operations. Migration never deletes Rubrica's source objects."""
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json

from fastapi import HTTPException
from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.storage_access import open_copy
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseDocument, EnterpriseIntegration, EnterpriseRequest, EnterpriseSignature
from core_api.modules.enterprise.machine_context import MachineContext
from core_api.modules.enterprise.request_router import utc
from core_api.modules.enterprise.storage_entities import MigrationDocument, MigrationItem, StorageDestination, StorageMigration
from core_api.modules.enterprise.storage_router import adapter_for
from core_api.modules.enterprise.usage import record_usage


def manifest(db, document):
    result = [("original", document.id, document.sha256, document.size_bytes)]
    signatures = db.scalars(select(EnterpriseSignature).join(EnterpriseRequest,
        EnterpriseRequest.id == EnterpriseSignature.request_id).where(EnterpriseRequest.document_id == document.id))
    for signature in signatures:
        result.append(("artifact", signature.id, signature.artifact_sha256, signature.artifact_size))
        evidence = evidence_bytes(signature)
        result.append(("evidence", signature.id, sha256(evidence).hexdigest(), len(evidence)))
    return result


def evidence_bytes(signature):
    canonical = json.dumps(signature.evidence, sort_keys=True, separators=(",", ":")).encode()
    if sha256(canonical).hexdigest() != signature.evidence_sha256:
        raise HTTPException(409, "Evidence integrity mismatch")
    return json.dumps({"evidence": signature.evidence, "sha256": signature.evidence_sha256,
        "hmac": signature.evidence_hmac, "provider_evidence": signature.provider_evidence},
        sort_keys=True, separators=(",", ":")).encode()


def source_stream(db, item, sandbox):
    if item.source_kind == "original":
        record = db.get(EnterpriseDocument, item.source_id)
        digest, size = record.sha256, record.size_bytes
    else:
        record = db.get(EnterpriseSignature, item.source_id)
        if item.source_kind == "evidence":
            data = evidence_bytes(record)
            if len(data) != item.size_bytes or sha256(data).hexdigest() != item.sha256:
                raise HTTPException(409, "Evidence changed during migration")
            return BytesIO(data)
        digest, size = record.artifact_sha256, record.artifact_size
    if (digest, size) != (item.sha256, item.size_bytes):
        raise HTTPException(409, "Source copy is unavailable or changed")
    document = db.get(EnterpriseDocument, item.document_id)
    compartment = db.get(EnterpriseCompartment, document.compartment_id)
    integration = db.get(EnterpriseIntegration, compartment.integration_id)
    context = MachineContext(integration.tenant_id, integration.id, compartment.id, "storage-migration", sandbox)
    return open_copy(db, context, item.source_kind, record, storage_factory=configured_document_storage)


def target_key(destination, job, item, prefix=""):
    suffix = "json" if item.source_kind == "evidence" else "pdf"
    prefix = prefix.strip("/")
    return (f"{prefix + '/' if prefix else ''}rubrica/{job.tenant_id}/"
            f"{'sandbox' if destination.sandbox else 'live'}/{job.integration_id}/{item.document_id}/"
            f"{item.source_kind}/{item.source_id}.{suffix}")


def prepare_document(db, job, entry):
    document = db.get(EnterpriseDocument, entry.document_id)
    # Same first lock as create_request: no new request can appear while a
    # terminal document manifest is captured. Also wait for any signature that
    # began before expiry to commit before collecting its final artefact.
    db.scalar(select(EnterpriseCompartment).where(EnterpriseCompartment.id == document.compartment_id).with_for_update())
    requests = list(db.scalars(select(EnterpriseRequest).where(EnterpriseRequest.document_id == document.id)
        .order_by(EnterpriseRequest.id).with_for_update().execution_options(populate_existing=True)))
    if any(request.status in {"draft", "open"} and utc(request.expires_at) > datetime.now(UTC) for request in requests):
        entry.status = "waiting_signature"
        return []
    if document.status != "ready":
        entry.status = "waiting_scan" if document.status == "quarantined" else "blocked"
        return []
    existing = {(item.source_kind, item.source_id): item for item in db.scalars(select(MigrationItem).where(
        MigrationItem.migration_id == job.id, MigrationItem.document_id == document.id))}
    items = []
    for kind, source_id, digest, size in manifest(db, document):
        item = existing.get((kind, source_id))
        if item is None:
            item = MigrationItem(migration_id=job.id, document_id=document.id, source_kind=kind,
                                 source_id=source_id, sha256=digest, size_bytes=size)
            db.add(item)
            db.flush()
        elif (item.sha256, item.size_bytes) != (digest, size):
            raise HTTPException(409, "Migration manifest changed")
        items.append(item)
    entry.status = "copying"
    return items


def process_job(db, job, *, limit=8):
    destination = db.get(StorageDestination, job.destination_id)
    integration = db.get(EnterpriseIntegration, job.integration_id)
    if (destination is None or destination.deleted_at is not None or destination.tenant_id != job.tenant_id
            or integration is None or integration.tenant_id != job.tenant_id or integration.sandbox != destination.sandbox
            or integration.environment != settings.ENVIRONMENT):
        raise HTTPException(409, "Invalid migration binding")
    entries = list(db.scalars(select(MigrationDocument).where(MigrationDocument.migration_id == job.id,
        MigrationDocument.status != "verified").order_by(MigrationDocument.updated_at, MigrationDocument.id).limit(limit)))
    for entry in entries:
        try:
            items = prepare_document(db, job, entry)
        except (HTTPException, ValueError):
            entry.status, entry.updated_at = "manifest_invalid", datetime.now(UTC)
            continue
        for item in items:
            if item.status == "verified":
                continue
            item.attempts += 1
            try:
                if destination.kind == "s3":
                    adapter = adapter_for(destination)
                    item.target_key = target_key(destination, job, item, adapter.configuration["prefix"])
                    adapter.ensure_object(item.target_key, item.sha256, item.size_bytes,
                        "application/json" if item.source_kind == "evidence" else "application/pdf",
                        lambda: source_stream(db, item, destination.sandbox))
                elif destination.kind == "rubrica":
                    with source_stream(db, item, destination.sandbox):
                        pass
                else:
                    item.status = "awaiting_delivery"
                    continue
                item.status, item.verified_at, item.error_code = "verified", datetime.now(UTC), None
                if destination.kind == "s3":
                    compartment = db.get(EnterpriseDocument, item.document_id).compartment_id
                    record_usage(db, MachineContext(job.tenant_id, job.integration_id, compartment,
                        "storage-migration", destination.sandbox), "storage.exported", item.id, bytes_count=item.size_bytes)
            except Exception:
                # No provider message, URL, key or credentials persist in status.
                item.status, item.error_code = "retry", "delivery_not_verified"
        if items and all(item.status == "verified" for item in items):
            entry.status = "verified"
        entry.updated_at = datetime.now(UTC)
    db.flush()
    remaining = db.scalar(select(MigrationDocument.id).where(MigrationDocument.migration_id == job.id,
        MigrationDocument.status != "verified").limit(1))
    job.status = "completed" if remaining is None else "pending"
    job.updated_at = datetime.now(UTC)


def migrate_once():
    with SessionLocal.begin() as db:
        job = db.scalar(select(StorageMigration).join(EnterpriseIntegration,
            EnterpriseIntegration.id == StorageMigration.integration_id).where(
            StorageMigration.status == "pending", EnterpriseIntegration.environment == settings.ENVIRONMENT
        ).order_by(StorageMigration.updated_at, StorageMigration.id).limit(1).with_for_update(of=StorageMigration, skip_locked=True))
        if job is None:
            return False
        process_job(db, job)
        return True
