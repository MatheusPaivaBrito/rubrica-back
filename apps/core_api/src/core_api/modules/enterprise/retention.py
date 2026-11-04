"""Resumable current-copy purge; external customer storage is never deleted."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import func, select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.document.storage import configured_document_storage
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseDocument, EnterpriseIntegration, EnterpriseRequest, EnterpriseSignature
from core_api.modules.enterprise.lifecycle import contract_view, lifecycle_for, notice, sync_contract
from core_api.modules.enterprise.lifecycle_entity import EnterpriseLifecycle, EnterpriseNotice, EnterprisePurgeCopy
from core_api.modules.enterprise.machine_context import MachineContext
from core_api.modules.enterprise.storage_access import copy_attributes
from core_api.modules.enterprise.storage_settings import for_mode
from core_api.modules.enterprise.usage import quota_row, record_usage
from core_api.modules.enterprise.usage_entity import EnterpriseUsageEvent


def schedule_purge(db, account, state, now):
    if not settings.ENTERPRISE_RETENTION_PURGE_ENABLED or contract_view(account, state, now=now)["status"] not in {"expired", "purging"}:
        return
    sources = list(db.execute(select(EnterpriseDocument, EnterpriseIntegration).join(EnterpriseCompartment,
        EnterpriseCompartment.id == EnterpriseDocument.compartment_id).join(EnterpriseIntegration,
        EnterpriseIntegration.id == EnterpriseCompartment.integration_id).where(
        EnterpriseIntegration.tenant_id == account.tenant_id, EnterpriseIntegration.environment == settings.ENVIRONMENT,
        EnterpriseDocument.status != "purged").order_by(EnterpriseDocument.id).limit(25)))
    for document, integration in sources:
        candidates = [("original", document)] + [("artifact", record) for record in db.scalars(select(EnterpriseSignature)
            .join(EnterpriseRequest, EnterpriseRequest.id == EnterpriseSignature.request_id).where(EnterpriseRequest.document_id == document.id))]
        for kind, record in candidates:
            key, _, size = copy_attributes(record, kind)
            if record.rubrica_copy_deleted_at is not None:
                continue
            if db.scalar(select(EnterprisePurgeCopy.id).where(EnterprisePurgeCopy.source_kind == kind,
                EnterprisePurgeCopy.source_id == record.id, EnterprisePurgeCopy.storage_key == key)) is None:
                db.add(EnterprisePurgeCopy(tenant_id=account.tenant_id, integration_id=integration.id,
                    document_id=document.id, sandbox=integration.sandbox, source_kind=kind, source_id=record.id,
                    storage_key=key, namespace=record.storage_namespace, size_bytes=size, next_attempt_at=now,
                    counted=record.deleted_at is None or db.scalar(select(EnterpriseUsageEvent.id).where(
                        EnterpriseUsageEvent.source_id == record.id, EnterpriseUsageEvent.tenant_id == account.tenant_id,
                        EnterpriseUsageEvent.kind == ("document.uploaded" if kind == "original" else "signature.completed")).limit(1)) is not None))
        # Tombstone only when all binaries are confirmed absent. Never drop a
        # reference after a denied deletion and conceal a retained object.
        if all(record.rubrica_copy_deleted_at is not None for _, record in candidates):
            document.deleted_at, document.status, document.filename = now, "purged", "[removed]"
    db.flush()
    remaining = db.scalar(select(EnterpriseDocument.id).join(EnterpriseCompartment,
        EnterpriseCompartment.id == EnterpriseDocument.compartment_id).join(EnterpriseIntegration,
        EnterpriseIntegration.id == EnterpriseCompartment.integration_id).where(EnterpriseIntegration.tenant_id == account.tenant_id,
        EnterpriseIntegration.environment == settings.ENVIRONMENT, EnterpriseDocument.status != "purged").limit(1))
    if remaining is None and state.purged_at is None:
        state.purge_started_at = state.purge_started_at or now
        state.purged_at, state.status = now, "purged"
        notice(db, account.tenant_id, "contract.current_copies_purged", str(state.revision), {"completed_at": now.isoformat(),
            "internal_retention_complete": False})


def synchronize_once(*, now=None):
    now = now or datetime.now(UTC)
    with SessionLocal.begin() as db:
        accounts = list(db.scalars(select(BillingAccountEntity).outerjoin(EnterpriseLifecycle,
            EnterpriseLifecycle.tenant_id == BillingAccountEntity.tenant_id).where(BillingAccountEntity.deleted_at.is_(None),
            BillingAccountEntity.tenant_id.in_(select(EnterpriseIntegration.tenant_id).where(
                EnterpriseIntegration.environment == settings.ENVIRONMENT)))
            .order_by(func.coalesce(EnterpriseLifecycle.updated_at, BillingAccountEntity.created_at)).limit(25)
            .with_for_update(of=BillingAccountEntity, skip_locked=True)))
        for account in accounts:
            state, _ = sync_contract(db, account, now=now)
            requests = list(db.scalars(select(EnterpriseRequest).join(EnterpriseCompartment,
                EnterpriseCompartment.id == EnterpriseRequest.compartment_id).join(EnterpriseIntegration,
                EnterpriseIntegration.id == EnterpriseCompartment.integration_id).where(EnterpriseIntegration.tenant_id == account.tenant_id,
                EnterpriseIntegration.environment == settings.ENVIRONMENT, EnterpriseRequest.status.in_(["draft", "open"]),
                EnterpriseRequest.expires_at <= now).order_by(EnterpriseRequest.id).limit(25).with_for_update(of=EnterpriseRequest)))
            for request in requests:
                from uuid import NAMESPACE_URL, uuid5
                from core_api.modules.enterprise.webhooks import enqueue
                integration = db.get(EnterpriseIntegration, db.get(EnterpriseCompartment, request.compartment_id).integration_id)
                request.status = "expired"
                enqueue(db, integration, uuid5(NAMESPACE_URL, f"request.expired:{request.id}"), "request.expired", {
                    "request_id": str(request.id), "document_id": str(request.document_id)})
            schedule_purge(db, account, state, now)
            state.updated_at = now
        return len(accounts)


def purge_once(*, now=None):
    if not settings.ENTERPRISE_RETENTION_PURGE_ENABLED:
        return False
    now = now or datetime.now(UTC)
    with SessionLocal.begin() as db:
        candidate = db.scalar(select(EnterprisePurgeCopy).join(EnterpriseIntegration,
            EnterpriseIntegration.id == EnterprisePurgeCopy.integration_id).where(
            EnterpriseIntegration.environment == settings.ENVIRONMENT, EnterprisePurgeCopy.status.in_(["pending", "retry"]),
            EnterprisePurgeCopy.next_attempt_at <= now).order_by(EnterprisePurgeCopy.next_attempt_at).limit(1))
        if candidate is None:
            return False
        account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == candidate.tenant_id)
            .with_for_update().execution_options(populate_existing=True))
        state = lifecycle_for(db, candidate.tenant_id, lock=True)
        if contract_view(account, state, now=now)["status"] not in {"expired", "purging"}:
            candidate.status = "cancelled"
            return True
        item = db.scalar(select(EnterprisePurgeCopy).where(EnterprisePurgeCopy.id == candidate.id,
            EnterprisePurgeCopy.status.in_(["pending", "retry"])).with_for_update().execution_options(populate_existing=True))
        if item is None:
            return False
        item.attempts += 1
        try:
            with db.begin_nested():
                document = db.get(EnterpriseDocument, item.document_id)
                db.scalar(select(EnterpriseCompartment).where(EnterpriseCompartment.id == document.compartment_id).with_for_update())
                requests = list(db.scalars(select(EnterpriseRequest).where(EnterpriseRequest.document_id == document.id)
                    .order_by(EnterpriseRequest.id).with_for_update()))
                for request in requests:
                    if request.status in {"draft", "open"}:
                        request.status = "cancelled"
                record = document if item.source_kind == "original" else db.get(EnterpriseSignature, item.source_id)
                key, _, size = copy_attributes(record, item.source_kind)
                if key != item.storage_key:
                    item.status = "superseded"
                    return True
                if record.rubrica_copy_deleted_at is None:
                    context = MachineContext(item.tenant_id, item.integration_id, document.compartment_id, "retention", item.sandbox)
                    quota = quota_row(db, context)
                    if item.counted and (quota.storage_bytes < size or (item.source_kind == "original" and quota.document_count < 1)):
                        raise ValueError("Storage meter requires reconciliation")
                    configured_document_storage(for_mode(settings, item.sandbox, item.namespace)).remove_copy(key)
                    record.rubrica_copy_deleted_at = now
                    if item.counted:
                        quota.storage_bytes -= size
                        if item.source_kind == "original":
                            quota.document_count -= 1
                    record_usage(db, context, "storage.removed", item.id, bytes_count=size if item.counted else 0, now=now)
                state.purge_started_at, state.status = state.purge_started_at or now, "purging"
                item.status, item.error_code = "deleted", None
        except Exception:
            item.status, item.error_code = "retry", "purge_not_confirmed"
            item.next_attempt_at = now + timedelta(seconds=min(300, 2 ** min(item.attempts, 8)))
        return True


def email_notice_once(*, now=None):
    from core_api.modules.billing.notification_client import request_billing_email
    from core_api.modules.tenant.tenant_entity import TenantMemberEntity
    now = now or datetime.now(UTC)
    with SessionLocal.begin() as db:
        item = db.scalar(select(EnterpriseNotice).where(EnterpriseNotice.email_complete.is_(False),
            EnterpriseNotice.next_attempt_at <= now, EnterpriseNotice.tenant_id.in_(select(EnterpriseIntegration.tenant_id).where(
                EnterpriseIntegration.environment == settings.ENVIRONMENT))).order_by(EnterpriseNotice.next_attempt_at)
            .limit(1).with_for_update(skip_locked=True))
        if item is None:
            return False
        recipients = list(db.scalars(select(TenantMemberEntity.auth_user_id).where(TenantMemberEntity.tenant_id == item.tenant_id,
            TenantMemberEntity.role == "admin", TenantMemberEntity.status == "active", TenantMemberEntity.deleted_at.is_(None))))
        done = set(item.delivered_to)
        item.attempts += 1
        labels = {"contract.suspended": "Seu acesso à API foi suspenso por cancelamento ou inadimplência.",
            "contract.reactivated": "Seu acesso à API foi regularizado.",
            "contract.purge_warning": "O prazo para retirar os arquivos está próximo do fim.",
            "contract.cycle_ending": "O encerramento do ciclo do contrato está próximo.",
            "contract.current_copies_purged": "A limpeza das cópias correntes dos arquivos foi concluída. O tratamento de cópias internas deve ser confirmado pelo operador."}
        dates = {"suspended_at": "Suspensão (UTC)", "delete_after": "Prazo de retirada e início da exclusão (UTC)",
                 "cycle_end": "Encerramento do ciclo (UTC)", "completed_at": "Conclusão (UTC)"}
        body = labels.get(item.kind, "Há uma atualização no contrato da API.") + "\n" + "\n".join(
            f"{label}: {item.payload[key]}" for key, label in dates.items() if item.payload.get(key))
        for recipient in [value for value in recipients if sha256(value.encode()).hexdigest() not in done][:10]:
            identity = sha256(recipient.encode()).hexdigest()
            if identity in done:
                continue
            try:
                request_billing_email(recipient=recipient, subject="Rubrica — aviso do contrato de API",
                    body=body
                    + "\nConsulte Integrações e API para ver as datas no seu fuso e retirar os arquivos. A migração não prorroga o prazo de recuperação.",
                    idempotency_key=f"enterprise-notice:{item.id}:{identity}")
                done.add(identity)
            except Exception:
                pass
        item.delivered_to = sorted(done)
        item.email_complete = bool(recipients) and all(sha256(recipient.encode()).hexdigest() in done for recipient in recipients)
        item.next_attempt_at = now + timedelta(seconds=min(3600, 2 ** min(item.attempts + 2, 12)))
        return True
