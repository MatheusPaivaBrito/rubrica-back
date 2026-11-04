"""Close only after physical copies are gone; backup proof is a separate barrier."""
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import select, update

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.enterprise.completion_entity import EnterpriseClosure
from core_api.modules.enterprise.execution_entity import EnterpriseJob, EnterpriseOperation
from core_api.modules.enterprise.entities import EnterpriseAuthorization, EnterpriseCompartment, EnterpriseDocument, EnterpriseIntegration, EnterpriseProvider, EnterpriseRequest, EnterpriseSignature, EnterpriseSigningSession
from core_api.modules.enterprise.lifecycle import utc
from core_api.modules.enterprise.lifecycle_entity import EnterpriseLifecycle, EnterpriseNotice, EnterpriseWebhook, EnterpriseWebhookDelivery
from core_api.modules.enterprise.storage_entities import CopyRemoval, StorageDestination, StorageMigration, StoragePolicy
from core_api.modules.signature_request.signature_request_entity import AuditEventEntity
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.storage_settings import for_mode


def closure_for(db, state):
    return db.scalar(select(EnterpriseClosure).where(EnterpriseClosure.tenant_id == state.tenant_id, EnterpriseClosure.revision == state.revision))


def complete(item):
    return bool(item and item.objects_verified_at and item.metadata_purged_at and item.credentials_retired_at and item.backups_verified_at)


def erase_metadata(db, state, now):
    integrations = list(db.scalars(select(EnterpriseIntegration.id).where(EnterpriseIntegration.tenant_id == state.tenant_id,
        EnterpriseIntegration.environment == settings.ENVIRONMENT).order_by(EnterpriseIntegration.id).with_for_update()))
    compartments = select(EnterpriseCompartment.id).where(EnterpriseCompartment.integration_id.in_(integrations))
    requests = select(EnterpriseRequest.id).where(EnterpriseRequest.compartment_id.in_(compartments))
    for document in db.scalars(select(EnterpriseDocument).where(EnterpriseDocument.compartment_id.in_(compartments))):
        document.filename, document.idempotency_key = "[removed]", f"erased:{document.id}"
    db.execute(update(EnterpriseRequest).where(EnterpriseRequest.id.in_(requests)).values(signers=[], status="purged"))
    for request in db.scalars(select(EnterpriseRequest).where(EnterpriseRequest.id.in_(requests))):
        request.idempotency_key = f"erased:{request.id}"
    db.execute(update(EnterpriseSignature).where(EnterpriseSignature.request_id.in_(requests)).values(evidence={}, evidence_hmac="", provider_evidence=None))
    for session in db.scalars(select(EnterpriseSigningSession).where(EnterpriseSigningSession.request_id.in_(requests))):
        from hashlib import sha256
        session.digest, session.expires_at = sha256(f"erased:{session.id}".encode()).hexdigest(), now
    db.execute(update(EnterpriseAuthorization).where(EnterpriseAuthorization.tenant_id == state.tenant_id).values(encrypted_attempt="", consumed_at=now))
    db.execute(update(EnterpriseJob).where(EnterpriseJob.integration_id.in_(integrations)).values(
        encrypted_payload=None, result=None, status="erased", owner=None, lease_until=None, error_code=None))
    db.execute(update(EnterpriseOperation).where(EnterpriseOperation.request_id.in_(requests)).values(
        encrypted_checkpoint=None, status="erased", error_code=None))
    db.execute(update(EnterpriseCompartment).where(EnterpriseCompartment.integration_id.in_(integrations)).values(name="[removed]", deleted_at=now))
    db.execute(update(EnterpriseIntegration).where(EnterpriseIntegration.id.in_(integrations)).values(name="[removed]", created_by="[erased]", enabled=False, deleted_at=now))
    db.execute(update(EnterpriseProvider).where(EnterpriseProvider.tenant_id == state.tenant_id).values(encrypted_configuration="", updated_by="[erased]", status="removed", deleted_at=now))
    db.execute(update(StorageDestination).where(StorageDestination.tenant_id == state.tenant_id).values(encrypted_configuration=None, name="[removed]", created_by="[erased]", deleted_at=now))
    db.execute(update(StorageMigration).where(StorageMigration.tenant_id == state.tenant_id).values(created_by="[erased]"))
    db.execute(update(StoragePolicy).where(StoragePolicy.integration_id.in_(integrations)).values(updated_by="[erased]"))
    db.execute(update(CopyRemoval).where(CopyRemoval.document_id.in_(select(EnterpriseDocument.id).where(
        EnterpriseDocument.compartment_id.in_(compartments)))).values(requested_by="[erased]"))
    endpoint_ids = select(EnterpriseWebhook.id).where(EnterpriseWebhook.integration_id.in_(integrations))
    db.execute(update(EnterpriseWebhookDelivery).where(EnterpriseWebhookDelivery.endpoint_id.in_(endpoint_ids)).values(payload={}, status="cancelled"))
    db.execute(update(EnterpriseWebhook).where(EnterpriseWebhook.integration_id.in_(integrations)).values(url="", encrypted_secret="", enabled=False))
    db.execute(update(EnterpriseNotice).where(EnterpriseNotice.tenant_id == state.tenant_id).values(delivered_to=[], email_complete=True))
    db.execute(update(AuditEventEntity).where(AuditEventEntity.entity_type == "tenant", AuditEventEntity.entity_id == state.tenant_id,
        AuditEventEntity.action.like("enterprise.%")).values(actor_id="[erased]", metadata_sanitized={}))


def finalize_once(*, now=None):
    now = now or datetime.now(UTC)
    with SessionLocal.begin() as db:
        state = db.scalar(select(EnterpriseLifecycle).where(EnterpriseLifecycle.purged_at.is_not(None),
            EnterpriseLifecycle.tenant_id.in_(select(EnterpriseIntegration.tenant_id).where(EnterpriseIntegration.environment == settings.ENVIRONMENT)))
            .order_by(EnterpriseLifecycle.updated_at).limit(1))
        if state is None:
            return False
        db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == state.tenant_id).with_for_update())
        state = db.scalar(select(EnterpriseLifecycle).where(EnterpriseLifecycle.id == state.id).with_for_update().execution_options(populate_existing=True))
        if not state.purged_at or not state.recovery_until or now < utc(state.recovery_until):
            return False
        item = closure_for(db, state)
        if item is None:
            item = EnterpriseClosure(id=uuid5(NAMESPACE_URL, f"enterprise.close:{state.tenant_id}:{state.revision}"),
                tenant_id=state.tenant_id, revision=state.revision, next_attempt_at=now)
            db.add(item)
            db.flush()
        if item.next_attempt_at and utc(item.next_attempt_at) > now:
            state.updated_at = now
            return False
        if item.objects_verified_at is None:
            # Current, sandbox and pre-isolation namespaces are all Rubrica-owned.
            empty = True
            for sandbox, namespace in ((False, "isolated-v1"), (True, "isolated-v1"), (True, "legacy")):
                storage = configured_document_storage(for_mode(settings, sandbox, namespace))
                empty = storage.purge_enterprise_namespace(state.tenant_id) and empty
            if not empty:
                state.updated_at = now
                return True
            item.objects_verified_at = now
        if item.metadata_purged_at is None:
            erase_metadata(db, state, now)
            item.metadata_purged_at = now
        if item.credentials_retired_at is None:
            item.attempts += 1
            try:
                if not settings.CORE_INTERNAL_SERVICE_KEY:
                    raise ValueError("Internal credential key is required")
                result = httpx.post(f"{settings.AUTH_API_URL.rstrip('/')}/internal/machine-credentials/retire-tenant",
                    headers={"X-Rubrica-Service": "core_api", "X-Rubrica-Service-Key": settings.CORE_INTERNAL_SERVICE_KEY},
                    json={"tenant_id": str(state.tenant_id), "environment": settings.ENVIRONMENT, "operation_id": str(item.id)}, timeout=5)
                if result.status_code != 200 or result.json().get("operation_id") != str(item.id) or result.json().get("retired") is not True:
                    raise ValueError("Retirement not acknowledged")
                item.credentials_retired_at, item.error_code = now, None
            except (httpx.HTTPError, ValueError):
                item.error_code = "auth_retirement_pending"
                item.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(item.attempts, 8)))
        if settings.ENTERPRISE_BACKUP_POLICY == "none" and settings.ENVIRONMENT == "development":
            item.backups_verified_at, item.backup_receipt = now, {"policy": "no_backups_development"}
        state.updated_at = now
        return True
