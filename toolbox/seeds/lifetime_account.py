"""Grant or revoke complimentary lifetime access for one exact tenant.

This command is deliberately available only to an operator with shell access. It
does not expose an HTTP endpoint and records every state change in billing_events.
"""

import argparse
import json
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.billing.billing_entity import BillingAccountEntity, BillingEventEntity
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from shared_kernel.time.datetime_service import DateTimeService


def _bounded(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must have at most {maximum} characters")
    return normalized


def change_lifetime_access(
    tenant_id: UUID,
    *,
    enabled: bool,
    actor: str,
    reason: str,
) -> bool:
    actor = _bounded(actor, "actor", 255)
    reason = _bounded(reason, "reason", 500)
    now = DateTimeService.utc_now()

    with SessionLocal.begin() as database:
        tenant = database.scalar(
            select(TenantEntity)
            .where(TenantEntity.id == tenant_id, TenantEntity.deleted_at.is_(None))
            .with_for_update()
        )
        if tenant is None:
            raise ValueError(f"Active tenant {tenant_id} was not found")

        account = database.scalar(
            select(BillingAccountEntity)
            .where(BillingAccountEntity.tenant_id == tenant_id)
            .with_for_update()
        )
        if account is None:
            account = BillingAccountEntity(tenant_id=tenant_id, status="not_configured")
            database.add(account)
            database.flush()
        elif account.deleted_at is not None:
            account.deleted_at = None

        if account.complimentary_lifetime is enabled:
            return False

        account.complimentary_lifetime = enabled
        if enabled:
            account.complimentary_granted_at = now
            account.complimentary_granted_by = actor
            account.complimentary_grant_reason = reason

        action = "granted" if enabled else "revoked"
        audit_payload = {
            "actor": actor,
            "enabled": enabled,
            "entitlement": "complimentary_lifetime",
            "reason": reason,
            "tenant_id": str(tenant_id),
        }
        encoded_payload = json.dumps(
            audit_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        database.add(
            BillingEventEntity(
                tenant_id=tenant_id,
                provider="rubrica_staff",
                provider_event_id=f"complimentary_lifetime:{uuid4()}",
                event_type=f"complimentary_lifetime.{action}",
                resource_id=str(tenant_id),
                payload_hash=sha256(encoded_payload).hexdigest(),
                payload_sanitized=audit_payload,
                status="processed",
                processed_at=now,
            )
        )
    return True


def tenant_id_for_owner(owner_email: str) -> UUID:
    normalized_email = _bounded(owner_email, "owner email", 255).lower()
    with SessionLocal() as database:
        tenant_ids = database.scalars(
            select(TenantEntity.id)
            .join(
                TenantMemberEntity,
                TenantMemberEntity.tenant_id == TenantEntity.id,
            )
            .where(
                TenantMemberEntity.auth_user_id == normalized_email,
                TenantMemberEntity.role == "admin",
                TenantMemberEntity.deleted_at.is_(None),
                TenantEntity.deleted_at.is_(None),
            )
            .order_by(TenantEntity.created_at)
        ).all()
    if not tenant_ids:
        raise ValueError(f"No active tenant was found for owner {normalized_email}")
    if len(tenant_ids) > 1:
        raise ValueError(
            f"Owner {normalized_email} has multiple tenants; use --tenant-id"
        )
    return tenant_ids[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage complimentary lifetime access for a Rubrica tenant."
    )
    parser.add_argument("action", choices=("grant", "revoke"))
    tenant = parser.add_mutually_exclusive_group(required=True)
    tenant.add_argument("--tenant-id", type=UUID)
    tenant.add_argument("--owner-email")
    parser.add_argument("--actor", required=True, help="Staff identity recorded in the audit event")
    parser.add_argument("--reason", required=True, help="Business reason recorded in the audit event")
    args = parser.parse_args()

    tenant_id = args.tenant_id or tenant_id_for_owner(args.owner_email)
    changed = change_lifetime_access(
        tenant_id,
        enabled=args.action == "grant",
        actor=args.actor,
        reason=args.reason,
    )
    state = "enabled" if args.action == "grant" else "disabled"
    result = "updated" if changed else "already in the requested state"
    print(f"[ok] Complimentary lifetime access {state} for {tenant_id}: {result}")


if __name__ == "__main__":
    main()
