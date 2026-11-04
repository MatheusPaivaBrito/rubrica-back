from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
import httpx
from sqlalchemy import case, func, select

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.enterprise.entities import EnterpriseCompartment, EnterpriseDocument, EnterpriseRequest, EnterpriseSignature
from core_api.modules.enterprise.machine_context import MachineContext, require_machine
from core_api.modules.enterprise.router import binding
from core_api.modules.enterprise.telemetry import internal_headers
from core_api.modules.enterprise.usage_entity import EnterpriseQuota, EnterpriseUsageEvent

router = APIRouter(tags=["enterprise usage"])


def canonical_summary(db, context, *, compartment_only=True):
    record = EnterpriseUsageEvent
    start = datetime.now(UTC) - timedelta(days=30)
    filters = [record.tenant_id == context.tenant_id, record.integration_id == context.integration_id,
               record.sandbox == context.sandbox, record.environment == settings.ENVIRONMENT, record.occurred_at >= start]
    if compartment_only:
        filters.append(record.compartment_id == context.compartment_id)
    columns = [
        func.coalesce(func.sum(case((record.kind == "signature.completed", record.units), else_=0)), 0).label("signatures"),
        func.coalesce(func.sum(case((record.billable.is_(True), record.units), else_=0)), 0).label("billable_signatures"),
        func.coalesce(func.sum(case((record.kind == "document.uploaded", record.bytes_count), else_=0)), 0).label("uploaded_bytes"),
        func.coalesce(func.sum(case((record.kind.in_(["download.completed", "download.partial"]), record.bytes_count), else_=0)), 0).label("downloaded_bytes"),
        func.coalesce(func.sum(case((record.kind == "api.request", record.units), else_=0)), 0).label("requests"),
        func.coalesce(func.sum(case((record.status_code >= 400, record.units), else_=0)), 0).label("errors"),
        func.coalesce(func.sum(record.amount_minor), 0).label("amount_minor"),
    ]
    totals = dict(db.execute(select(*columns).where(*filters)).mappings().one())
    tokens = [dict(row) for row in db.execute(select(record.token_public_id, *columns).where(*filters)
        .group_by(record.token_public_id).order_by(record.token_public_id).limit(100)).mappings()]
    compartments = select(EnterpriseCompartment.id).where(EnterpriseCompartment.integration_id == context.integration_id)
    if compartment_only:
        compartments = compartments.where(EnterpriseCompartment.id == context.compartment_id)
    stored_originals = db.scalar(select(func.coalesce(func.sum(EnterpriseDocument.size_bytes), 0)).where(
        EnterpriseDocument.compartment_id.in_(compartments), EnterpriseDocument.deleted_at.is_(None),
        EnterpriseDocument.rubrica_copy_deleted_at.is_(None)))
    stored_artifacts = db.scalar(select(func.coalesce(func.sum(EnterpriseSignature.artifact_size), 0))
        .join(EnterpriseRequest, EnterpriseRequest.id == EnterpriseSignature.request_id).where(
            EnterpriseRequest.compartment_id.in_(compartments), EnterpriseSignature.deleted_at.is_(None),
            EnterpriseSignature.rubrica_copy_deleted_at.is_(None)))
    response = {"source": "core_usage_ledger", "sandbox": context.sandbox, "window_start": start,
                "totals": totals, "tokens": tokens, "token_list_limit": 100,
                "storage_bytes": stored_originals + stored_artifacts,
                "currency": "BRL", "price_version": "enterprise-zero-v1", "price_per_gb_month_minor": 0}
    if not compartment_only:
        quota = db.scalar(select(EnterpriseQuota).where(EnterpriseQuota.tenant_id == context.tenant_id,
            EnterpriseQuota.sandbox == context.sandbox))
        response["tenant_storage_bytes"] = quota.storage_bytes if quota else 0
        response["tenant_included_storage_bytes"] = 0 if context.sandbox else 1_000_000_000
    return response


@router.get("/api/v1/compartments/{compartment_id}/usage")
@router.get("/api/v1/sandbox/compartments/{compartment_id}/usage")
def machine_usage(context: MachineContext = Depends(require_machine("usage:read"))):
    with SessionLocal() as db:
        return canonical_summary(db, context)


def admin_context(db, tenant_id, integration_id, context):
    item = binding(db, tenant_id, integration_id, context)
    # No compartment is selected for the tenant administrator's integration view.
    return MachineContext(item.tenant_id, item.id, item.id, "admin-summary", item.sandbox)


@router.get("/enterprise/tenants/{tenant_id}/integrations/{integration_id}/usage")
def admin_usage(tenant_id: UUID, integration_id: UUID,
                context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        scope = admin_context(db, tenant_id, integration_id, context)
        return canonical_summary(db, scope, compartment_only=False)


@router.get("/enterprise/tenants/{tenant_id}/integrations/{integration_id}/telemetry")
def admin_telemetry(tenant_id: UUID, integration_id: UUID,
                    context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        scope = admin_context(db, tenant_id, integration_id, context)
    if not settings.OBSERVABILITY_INTERNAL_SERVICE_KEY:
        return {"available": False}
    try:
        result = httpx.get(f"{settings.OBSERVABILITY_API_URL.rstrip('/')}/internal/observability/enterprise/summary",
            headers=internal_headers(), params={"tenant_id": str(tenant_id), "integration_id": str(integration_id),
                                               "sandbox": str(scope.sandbox).lower()}, timeout=2)
        if result.status_code != 200:
            return {"available": False}
        return {"available": True, "projection": result.json()}
    except (httpx.HTTPError, ValueError):
        return {"available": False}
