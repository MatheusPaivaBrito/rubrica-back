"""Bounded cleanup of disposable API data; live accepted documents are retained."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import or_, select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.entities import EnterpriseAuthorization, EnterpriseCompartment, EnterpriseDocument, EnterpriseIntegration, EnterpriseRequest, EnterpriseSignature, EnterpriseSigningSession
from core_api.modules.enterprise.execution_entity import EnterpriseJob
from core_api.modules.enterprise.machine_context import MachineContext
from core_api.modules.enterprise.storage_access import copy_attributes
from core_api.modules.enterprise.storage_settings import for_mode
from core_api.modules.enterprise.usage import quota_row, record_usage


def cleanup_once(*, now=None):
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=30)
    with SessionLocal.begin() as db:
        candidate = db.execute(select(EnterpriseDocument, EnterpriseIntegration).join(EnterpriseCompartment,
            EnterpriseCompartment.id == EnterpriseDocument.compartment_id).join(EnterpriseIntegration,
            EnterpriseIntegration.id == EnterpriseCompartment.integration_id).where(
            EnterpriseIntegration.environment == settings.ENVIRONMENT, EnterpriseDocument.created_at <= cutoff,
            EnterpriseDocument.deleted_at.is_(None), or_(EnterpriseIntegration.sandbox.is_(True),
                EnterpriseDocument.status.in_(["rejected", "quarantined"])))
            .order_by(EnterpriseDocument.created_at).limit(1)).first()
        if candidate:
            document, integration = candidate
            db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == integration.tenant_id).with_for_update())
            db.scalar(select(EnterpriseCompartment).where(EnterpriseCompartment.id == document.compartment_id).with_for_update())
            document = db.scalar(select(EnterpriseDocument).where(EnterpriseDocument.id == document.id).with_for_update()
                .execution_options(populate_existing=True))
            # Recheck after acquiring the account/document locks.
            if document.deleted_at or (not integration.sandbox and document.status not in {"rejected", "quarantined"}):
                return False
            requests = list(db.scalars(select(EnterpriseRequest).where(EnterpriseRequest.document_id == document.id)
                .order_by(EnterpriseRequest.id).with_for_update()))
            if not integration.sandbox and any(item.status in {"open", "completed"} for item in requests):
                return False
            context = MachineContext(integration.tenant_id, integration.id, document.compartment_id, "retention", integration.sandbox)
            candidates = [("original", document)] + [("artifact", item) for item in db.scalars(select(EnterpriseSignature)
                .where(EnterpriseSignature.request_id.in_([item.id for item in requests])))]
            quota = quota_row(db, context)
            for kind, item in candidates:
                if item.rubrica_copy_deleted_at:
                    continue
                key, _, size = copy_attributes(item, kind)
                if quota.storage_bytes < size or (kind == "original" and quota.document_count < 1):
                    raise ValueError("Storage meter requires reconciliation before cleanup")
                configured_document_storage(for_mode(settings, integration.sandbox, item.storage_namespace)).remove_copy(key)
                item.rubrica_copy_deleted_at = now
                quota.storage_bytes -= size
                if kind == "original":
                    quota.document_count -= 1
                record_usage(db, context, "storage.removed", uuid5(NAMESPACE_URL, f"enterprise.cleanup:{kind}:{item.id}"), bytes_count=size, now=now)
            for item in requests:
                item.status, item.signers = "purged", []
            for kind, item in candidates:
                if kind == "artifact":
                    item.evidence, item.evidence_hmac, item.provider_evidence = {}, "", None
            document.status, document.filename, document.deleted_at = "purged", "[removed]", now
        integrations = select(EnterpriseIntegration.id).where(EnterpriseIntegration.environment == settings.ENVIRONMENT)
        for job in db.scalars(select(EnterpriseJob).where(EnterpriseJob.integration_id.in_(integrations),
            EnterpriseJob.created_at <= cutoff, EnterpriseJob.status != "running", EnterpriseJob.encrypted_payload.is_not(None)).limit(50)):
            job.encrypted_payload, job.result = None, None
            if job.status == "queued":
                job.status, job.error_code = "failed", "processing_payload_expired"
        for attempt in db.scalars(select(EnterpriseAuthorization).where(EnterpriseAuthorization.expires_at <= now,
            EnterpriseAuthorization.encrypted_attempt != "").limit(50)):
            attempt.encrypted_attempt, attempt.consumed_at = "", now
        # Expired sessions remain hash tombstones; never retain a reusable secret.
        for session in db.scalars(select(EnterpriseSigningSession).where(EnterpriseSigningSession.expires_at <= cutoff).limit(50)):
            session.digest = sha256(f"expired:{session.id}".encode()).hexdigest()
        return candidate is not None
