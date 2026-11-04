from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.enterprise.lifecycle import contract_view, lifecycle_for
from core_api.modules.enterprise.lifecycle_entity import EnterpriseNotice, EnterpriseWebhook, EnterpriseWebhookDelivery
from core_api.modules.enterprise.provider_vault import encrypt_configuration
from core_api.modules.enterprise.router import binding
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseRequest
from core_api.modules.enterprise.webhooks import webhook_url
from core_api.modules.tenant.tenant_service import tenant_service

router = APIRouter(prefix="/enterprise/tenants/{tenant_id}", tags=["enterprise lifecycle and webhooks"])


@router.get("/integrations/{integration_id}/recovery-requests")
def recovery_requests(tenant_id: UUID, integration_id: UUID,
                       context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        binding(db, tenant_id, integration_id, context, recovery=True)
        return [{"id": item.id, "document_id": item.document_id, "status": item.status, "expires_at": item.expires_at}
            for item in db.scalars(select(EnterpriseRequest).join(EnterpriseCompartment,
                EnterpriseCompartment.id == EnterpriseRequest.compartment_id).where(EnterpriseCompartment.integration_id == integration_id,
                EnterpriseRequest.status.in_(["draft", "open"])).order_by(EnterpriseRequest.expires_at).limit(50))]


@router.post("/integrations/{integration_id}/recovery-requests/{request_id}/cancel")
def cancel_recovery_request(tenant_id: UUID, integration_id: UUID, request_id: UUID,
                            context: AuthContext = Depends(require_permission("documents:write"))):
    from core_api.modules.enterprise.request_router import audit
    from core_api.modules.enterprise.machine_context import MachineContext
    with SessionLocal.begin() as db:
        integration = binding(db, tenant_id, integration_id, context, recovery=True)
        request = db.scalar(select(EnterpriseRequest).join(EnterpriseCompartment,
            EnterpriseCompartment.id == EnterpriseRequest.compartment_id).where(EnterpriseRequest.id == request_id,
                EnterpriseCompartment.integration_id == integration_id).with_for_update(of=EnterpriseRequest))
        if request is None:
            raise HTTPException(404, "Request not found")
        if request.status in {"draft", "open"}:
            request.status = "cancelled"
            audit(db, MachineContext(tenant_id, integration_id, request.compartment_id, "admin-recovery", integration.sandbox),
                  request, "enterprise.request.cancelled")
        return {"id": request.id, "status": request.status}


@router.get("/contract")
def contract_status(tenant_id: UUID, context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        tenant_service.require_role(db, tenant_id, context.subject, {"admin"})
        account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id,
            BillingAccountEntity.deleted_at.is_(None)))
        state = lifecycle_for(db, tenant_id)
        if account is None or (account.current_product_code != "rubrica_enterprise" and state is None):
            raise HTTPException(403, "Enterprise contract required")
        result = contract_view(account, state)
        from core_api.modules.enterprise.closure import closure_for, complete
        closure = closure_for(db, state) if state else None
        result["internal_retention_complete"] = complete(closure)
        result["closure_id"] = closure.id if closure else None
        result["metadata_erased"] = bool(closure and closure.metadata_purged_at)
        result["credentials_retired"] = bool(closure and closure.credentials_retired_at)
        result["backups_verified"] = bool(closure and closure.backups_verified_at)
        result["recontract_allowed"] = bool(complete(closure) and account.current_product_code == "rubrica_enterprise"
            and account.status == "active" and not account.cancel_at_period_end)
        result["automatic_current_copy_purge_enabled"] = settings.ENTERPRISE_RETENTION_PURGE_ENABLED
        result["notices"] = [{"id": item.id, "kind": item.kind, "payload": item.payload, "created_at": item.created_at,
                              "email_delivered": item.email_complete} for item in db.scalars(select(EnterpriseNotice).where(
                                  EnterpriseNotice.tenant_id == tenant_id).order_by(EnterpriseNotice.created_at.desc()).limit(30))]
        return result


class RecontractRequest(BaseModel):
    confirm_empty_contract: bool
    closure_id: UUID


@router.post("/contract/reopen")
def reopen_contract(tenant_id: UUID, payload: RecontractRequest,
                    context: AuthContext = Depends(require_permission("documents:write"))):
    from core_api.modules.enterprise.closure import complete
    if not payload.confirm_empty_contract:
        raise HTTPException(422, "Confirm a new empty contract; erased data cannot be restored")
    with SessionLocal.begin() as db:
        tenant_service.require_role(db, tenant_id, context.subject, {"admin"})
        account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id,
            BillingAccountEntity.deleted_at.is_(None)).with_for_update())
        state = lifecycle_for(db, tenant_id, lock=True)
        from core_api.modules.enterprise.completion_entity import EnterpriseClosure
        closure = db.scalar(select(EnterpriseClosure).where(EnterpriseClosure.id == payload.closure_id,
            EnterpriseClosure.tenant_id == tenant_id).with_for_update())
        if closure and closure.reopened_at:
            return {"status": "already_reopened", "revision": closure.revision + 1, "data_restored": False}
        if not (account and account.current_product_code == "rubrica_enterprise" and account.status == "active"
                and not account.cancel_at_period_end and state and state.purged_at and complete(closure) and closure.revision == state.revision):
            raise HTTPException(409, "Paid active contract and verified complete closure are required")
        now = datetime.now(UTC)
        closure.reopened_at = now
        state.suspended_at = state.recovery_until = state.failure_cutoff = state.purge_started_at = state.purged_at = None
        state.status, state.revision = "active", state.revision + 1
        account.usage_period_starts_at = now
        tenant_service._audit(db, tenant_id, "contract-admin", "enterprise.contract.reopened", {"revision": state.revision,
            "previous_closure": str(closure.id), "data_restored": False})
        return {"status": "active", "revision": state.revision, "data_restored": False, "new_tokens_required": True}


class WebhookConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)


@router.put("/integrations/{integration_id}/webhook")
def configure_webhook(tenant_id: UUID, integration_id: UUID, payload: WebhookConfiguration, response: Response,
                       context: AuthContext = Depends(require_permission("documents:write"))):
    webhook_url(payload.url)
    secret = token_urlsafe(32)
    with SessionLocal.begin() as db:
        integration = binding(db, tenant_id, integration_id, context)
        item = db.scalar(select(EnterpriseWebhook).where(EnterpriseWebhook.integration_id == integration_id).with_for_update())
        if item is None:
            item = EnterpriseWebhook(id=uuid4(), integration_id=integration_id, url=payload.url, secret_version=1)
            db.add(item)
        elif item.url != payload.url:
            if item.enabled:
                raise HTTPException(409, "Disable the current endpoint before changing its URL")
            db.execute(update(EnterpriseWebhookDelivery).where(EnterpriseWebhookDelivery.endpoint_id == item.id,
                EnterpriseWebhookDelivery.status == "pending").values(status="dead", error_code="endpoint_replaced"))
            item.secret_version += 1
        else:
            item.secret_version += 1
        item.url, item.enabled = payload.url, True
        item.encrypted_secret = encrypt_configuration(tenant_id, f"webhook:{item.id}", integration.sandbox,
            item.secret_version, {"secret": secret})
        tenant_service._audit(db, tenant_id, context.subject, "enterprise.webhook.rotated",
                              {"integration_id": str(integration_id), "version": item.secret_version})
        response.headers["Cache-Control"] = "private, no-store"
        return {"id": item.id, "url": item.url, "secret": secret, "version": item.secret_version,
                "receiver_replay_window_seconds": 300}


@router.get("/integrations/{integration_id}/webhook")
def webhook_status(tenant_id: UUID, integration_id: UUID,
                    context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        binding(db, tenant_id, integration_id, context, recovery=True)
        item = db.scalar(select(EnterpriseWebhook).where(EnterpriseWebhook.integration_id == integration_id))
        if item is None:
            return {"configured": False, "deliveries": []}
        deliveries = [{"id": row.id, "event_id": row.event_id, "status": row.status, "attempts": row.attempts,
                       "error_code": row.error_code} for row in db.scalars(select(EnterpriseWebhookDelivery).where(
            EnterpriseWebhookDelivery.endpoint_id == item.id).order_by(EnterpriseWebhookDelivery.created_at.desc()).limit(50))]
        return {"configured": True, "url": item.url, "enabled": item.enabled, "version": item.secret_version, "deliveries": deliveries}


@router.delete("/integrations/{integration_id}/webhook", status_code=204)
def disable_webhook(tenant_id: UUID, integration_id: UUID,
                     context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal.begin() as db:
        binding(db, tenant_id, integration_id, context, recovery=True)
        item = db.scalar(select(EnterpriseWebhook).where(EnterpriseWebhook.integration_id == integration_id).with_for_update())
        if item:
            item.enabled = False


@router.post("/integrations/{integration_id}/webhook/deliveries/{delivery_id}/replay")
def replay(tenant_id: UUID, integration_id: UUID, delivery_id: UUID,
            context: AuthContext = Depends(require_permission("documents:write"))):
    with SessionLocal.begin() as db:
        binding(db, tenant_id, integration_id, context, recovery=True)
        item = db.scalar(select(EnterpriseWebhookDelivery).join(EnterpriseWebhook,
            EnterpriseWebhook.id == EnterpriseWebhookDelivery.endpoint_id).where(EnterpriseWebhook.integration_id == integration_id,
            EnterpriseWebhook.enabled.is_(True), EnterpriseWebhookDelivery.id == delivery_id).with_for_update(of=EnterpriseWebhookDelivery))
        if item is None:
            raise HTTPException(404, "Delivery not found or endpoint disabled")
        if item.status != "dead":
            raise HTTPException(409, "Only failed deliveries can be replayed")
        item.status, item.next_attempt_at, item.retry_until = "pending", datetime.now(UTC), datetime.now(UTC) + timedelta(hours=24)
        tenant_service._audit(db, tenant_id, context.subject, "enterprise.webhook.replayed", {"delivery_id": str(item.id)})
        return {"event_id": item.event_id, "status": item.status}
