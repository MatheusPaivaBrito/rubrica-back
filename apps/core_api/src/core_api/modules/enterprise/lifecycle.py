"""One contractual clock; operational authorization never waits for the poller."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.enterprise.lifecycle_entity import EnterpriseLifecycle, EnterpriseNotice

CYCLE = timedelta(days=30)


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def cycle_end(account, now):
    anchor = utc(account.usage_period_starts_at or account.created_at)
    return anchor + (max(0, (now - anchor) // CYCLE) + 1) * CYCLE


def contract_view(account, state=None, *, now=None):
    now = utc(now or datetime.now(UTC))
    if account is None:
        return {"status": "unavailable", "operational": False, "recovery": False, "suspends_at": None, "delete_after": None}
    end = cycle_end(account, now)
    eligible = account.current_product_code == "rubrica_enterprise"
    delinquent = account.status in {"past_due", "unpaid", "paused", "cancelled"} or not eligible
    cutoff = None
    if account.cancel_at_period_end:
        cutoff = utc(account.cancels_at or account.current_period_ends_at or end)
    if delinquent:
        failure = getattr(state, "failure_cutoff", None) if state else None
        debt_cutoff = utc((account.updated_at or now) if not eligible else (failure or account.current_period_ends_at or account.updated_at or now))
        cutoff = min(cutoff, debt_cutoff) if cutoff else debt_cutoff
    restored = eligible and account.status == "active" and not account.cancel_at_period_end
    if state and state.suspended_at and state.recovery_until and now >= utc(state.recovery_until):
        restored = False  # Payment after the deadline cannot promise recovery of expired data.
    if state and state.purge_started_at is not None:
        status = "purged" if state.purged_at else "purging"
        return {"status": status, "operational": False, "recovery": False,
                "suspends_at": state.suspended_at, "delete_after": state.recovery_until, "cycle_end": end}
    if restored:
        cutoff = None
    elif state and state.suspended_at and not restored:
        cutoff = min(utc(state.suspended_at), cutoff) if cutoff else utc(state.suspended_at)
    allowed = eligible and account.status in {"active", "past_due", "cancelled", "unpaid", "paused"} and (cutoff is None or now < cutoff)
    suspended = cutoff is not None and now >= cutoff
    deadline = cutoff + CYCLE if cutoff else None
    return {"status": "recovery" if suspended and now < deadline else "expired" if suspended else "cancellation_pending" if cutoff else "active" if allowed else "unavailable",
            "operational": allowed, "recovery": suspended and now < deadline,
            "suspends_at": cutoff, "delete_after": deadline, "cycle_end": end}


def lifecycle_for(db, tenant_id, *, lock=False):
    statement = select(EnterpriseLifecycle).where(EnterpriseLifecycle.tenant_id == tenant_id)
    return db.scalar(statement.with_for_update() if lock else statement)


def require_operational(db, account, *, now=None):
    state = lifecycle_for(db, account.tenant_id) if account else None
    if not contract_view(account, state, now=now)["operational"]:
        raise HTTPException(403, "Enterprise operations suspended; the administrator may retrieve files during recovery")


def lock_operational(db, tenant_id):
    account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id,
        BillingAccountEntity.deleted_at.is_(None)).with_for_update().execution_options(populate_existing=True))
    require_operational(db, account)
    return account


def notice(db, tenant_id, kind, reference, payload):
    exists = db.scalar(select(EnterpriseNotice.id).where(EnterpriseNotice.tenant_id == tenant_id,
        EnterpriseNotice.kind == kind, EnterpriseNotice.reference == reference))
    if not exists:
        item = EnterpriseNotice(tenant_id=tenant_id, kind=kind, reference=reference, payload=payload)
        db.add(item)
        db.flush()
        from core_api.modules.enterprise.webhooks import enqueue_notice
        enqueue_notice(db, item)


def sync_contract(db, account, *, now=None):
    now = utc(now or datetime.now(UTC))
    state = lifecycle_for(db, account.tenant_id, lock=True)
    if state is None:
        state = EnterpriseLifecycle(id=uuid4(), tenant_id=account.tenant_id)
        db.add(state)
        db.flush()
    view = contract_view(account, state, now=now)
    if view["operational"] and state.suspended_at:
        notice(db, account.tenant_id, "contract.reactivated", str(state.revision), {})
        state.suspended_at = state.recovery_until = state.failure_cutoff = None
        state.revision += 1
    if view["suspends_at"] and now >= utc(view["suspends_at"]) and not state.suspended_at:
        state.suspended_at, state.recovery_until = view["suspends_at"], view["delete_after"]
        notice(db, account.tenant_id, "contract.suspended", str(state.revision), {
            "suspended_at": utc(state.suspended_at).isoformat(), "delete_after": utc(state.recovery_until).isoformat()})
    if view.get("cycle_end") and timedelta(0) < utc(view["cycle_end"]) - now <= timedelta(days=7):
        notice(db, account.tenant_id, "contract.cycle_ending", utc(view["cycle_end"]).isoformat(), {
            "cycle_end": utc(view["cycle_end"]).isoformat(),
            "suspends_at": utc(view["suspends_at"]).isoformat() if view["suspends_at"] else None,
            "delete_after": utc(view["delete_after"]).isoformat() if view["delete_after"] else None})
    if view["recovery"] and utc(view["delete_after"]) - now <= timedelta(days=7):
        notice(db, account.tenant_id, "contract.purge_warning", str(state.revision), {"delete_after": utc(view["delete_after"]).isoformat()})
    state.status = view["status"]
    return state, view


def mark_payment_failure(db, tenant_id, cutoff):
    account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id))
    if account and account.current_product_code == "rubrica_enterprise":
        state = lifecycle_for(db, tenant_id, lock=True)
        if state is None:
            state = EnterpriseLifecycle(tenant_id=tenant_id)
            db.add(state)
        if state.failure_cutoff is None:
            state.failure_cutoff = utc(cutoff)


def regularize_contract(db, account, *, now=None):
    """Billing holds the account lock: record timely regularization in the
    payment transaction, so a delayed poll cannot purge an already paid tenant."""
    now = utc(now or datetime.now(UTC))
    if account.current_product_code != "rubrica_enterprise" or account.status != "active" or account.cancel_at_period_end:
        return
    state = lifecycle_for(db, account.tenant_id, lock=True)
    if state and state.purge_started_at is None and (state.recovery_until is None or now < utc(state.recovery_until)):
        if state.suspended_at:
            notice(db, account.tenant_id, "contract.reactivated", str(state.revision), {})
            state.revision += 1
        state.suspended_at = state.recovery_until = state.failure_cutoff = None
        state.status = "active"
