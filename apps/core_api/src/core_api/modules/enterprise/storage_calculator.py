"""Logical bytes and exact byte-time above the tenant allowance; no invoices."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import Depends, HTTPException, Query
from sqlalchemy import case, select

from core_api.infrastructure.auth_context import AuthContext, require_permission
from core_api.infrastructure.database.connection import SessionLocal
from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.enterprise.router import require_storage_access as require_enterprise
from core_api.modules.enterprise.storage_router import router
from core_api.modules.enterprise.usage_entity import EnterpriseQuota, EnterpriseUsageEvent
from uuid import UUID

GB = 1_000_000_000
CYCLE = timedelta(days=30)


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def byte_time(current_bytes, changes, start, now, allowance=GB):
    """Reconstruct the opening balance, then integrate excess piecewise."""
    balance = current_bytes - sum(delta for _, delta in changes)
    if balance < 0 or current_bytes < 0:
        raise HTTPException(409, "Storage meter requires reconciliation")
    previous, total = start, Decimal(0)
    for instant, delta in sorted(changes, key=lambda entry: entry[0]):
        if instant < start or instant > now:
            raise ValueError("Storage changes must belong to the calculation window")
        total += Decimal(max(0, balance - allowance)) * Decimal((instant - previous) // timedelta(microseconds=1)) / 1_000_000
        balance += delta
        if balance < 0:
            raise HTTPException(409, "Storage meter requires reconciliation")
        previous = instant
    total += Decimal(max(0, balance - allowance)) * Decimal((now - previous) // timedelta(microseconds=1)) / 1_000_000
    return total


def calculate(db, tenant_id, sandbox, *, now=None):
    now = aware(now or datetime.now(UTC))
    account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id,
                       BillingAccountEntity.deleted_at.is_(None)))
    if account is None:
        raise HTTPException(404, "Billing account not found")
    anchor = aware(account.usage_period_starts_at or account.created_at)
    if anchor > now:
        raise HTTPException(409, "Billing cycle has not started")
    start = anchor + ((now - anchor) // CYCLE) * CYCLE
    event = EnterpriseUsageEvent
    # One SQL statement gives quota and deltas the same MVCC snapshot, even
    # while uploads commit. A LEFT JOIN also retains tenants with no changes.
    delta = case((event.kind == "storage.removed", -event.bytes_count), else_=event.bytes_count)
    rows = list(db.execute(select(EnterpriseQuota.storage_bytes, event.occurred_at, delta).outerjoin(
        event, (event.tenant_id == EnterpriseQuota.tenant_id) & (event.sandbox == EnterpriseQuota.sandbox)
        & (event.environment == settings.ENVIRONMENT) & (event.occurred_at >= start) & (event.occurred_at <= now)
        & event.kind.in_(["document.uploaded", "signature.completed", "storage.added", "storage.removed"])
    ).where(EnterpriseQuota.tenant_id == tenant_id, EnterpriseQuota.sandbox == sandbox)))
    current = rows[0][0] if rows else 0
    changes = [(aware(instant), count) for _, instant, count in rows if instant is not None]
    # Sandbox does not consume the commercial tenant allowance or create fees.
    included = settings.ENTERPRISE_SANDBOX_STORAGE_BYTES if sandbox else GB
    seconds = byte_time(current, changes, start, now, included)
    return {"sandbox": sandbox, "cycle_start": start, "cycle_end": start + CYCLE,
            "current_bytes": current, "included_bytes": included, "excess_bytes": max(0, current - included),
            "excess_byte_seconds": str(seconds), "accrued_gb_month": str(seconds / (GB * 30 * 86400)),
            "projected_full_month_gb": str(Decimal(max(0, current - included)) / GB),
            "currency": "BRL", "price_per_gb_month_minor": 0, "accrued_amount_minor": 0,
            "projected_amount_minor": 0, "price_version": "enterprise-zero-v1",
            "measurement": "logical_originals_and_signature_artifacts; decimal_GB; 30_days",
            "estimate_only": True}


@router.get("/calculator")
def calculator(tenant_id: UUID, sandbox: bool = Query(default=False),
               context: AuthContext = Depends(require_permission("documents:read"))):
    with SessionLocal() as db:
        require_enterprise(db, tenant_id, context)
        return calculate(db, tenant_id, sandbox)
