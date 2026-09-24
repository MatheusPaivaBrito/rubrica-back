"""Convert an existing tenant to business and attach an authorized member.

The CNPJ is read with ``getpass`` so it is not exposed in shell history or
process arguments. The command is idempotent and never moves or deletes the
member's personal tenant.
"""

import argparse
from dataclasses import dataclass
from getpass import getpass
from uuid import UUID

from sqlalchemy import select

from core_api.infrastructure.database.connection import SessionLocal
from core_api.modules.billing.billing_service import billing_service
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_identity import InvalidBusinessIdentifierError, protect_cnpj
from core_api.modules.tenant.tenant_service import tenant_service
from shared_kernel.time.datetime_service import DateTimeService


@dataclass(frozen=True)
class BusinessTenantMigrationResult:
    tenant_id: UUID
    registration_masked: str
    tenant_changed: bool
    member_changed: bool


def _email(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized or len(normalized) > 255:
        raise ValueError(f"{field} must be a valid email")
    return normalized


def _legal_name(value: str) -> str:
    normalized = value.strip()
    if len(normalized) < 2 or len(normalized) > 240:
        raise ValueError("legal name must contain 2 to 240 characters")
    return normalized


def migrate_business_tenant(
    *,
    owner_email: str,
    member_email: str,
    legal_name: str,
    cnpj: str,
    actor: str,
) -> BusinessTenantMigrationResult:
    owner = _email(owner_email, "owner email")
    member_email = _email(member_email, "member email")
    legal_name = _legal_name(legal_name)
    actor = _email(actor, "actor")
    encrypted, lookup, masked = protect_cnpj(cnpj)

    with SessionLocal.begin() as database:
        tenants = database.scalars(
            select(TenantEntity)
            .join(TenantMemberEntity, TenantMemberEntity.tenant_id == TenantEntity.id)
            .where(
                TenantMemberEntity.auth_user_id == owner,
                TenantMemberEntity.role == "admin",
                TenantMemberEntity.status == "active",
                TenantMemberEntity.deleted_at.is_(None),
                TenantEntity.deleted_at.is_(None),
            )
            .order_by(TenantEntity.created_at)
            .with_for_update()
        ).all()
        if not tenants:
            raise ValueError(f"No active tenant was found for owner {owner}")
        if len(tenants) > 1:
            raise ValueError(f"Owner {owner} has multiple tenants; migration is ambiguous")
        tenant = tenants[0]
        if not billing_service.business_features_enabled(database, tenant.id):
            raise WorkflowError("Professional or complimentary lifetime access is required", 403)

        tenant_changed = False
        if tenant.kind == "business":
            if tenant.registration_lookup_hmac != lookup:
                raise ValueError("The tenant is already business with another protected CNPJ")
        else:
            duplicate = database.scalar(
                select(TenantEntity.id).where(
                    TenantEntity.registration_lookup_hmac == lookup,
                    TenantEntity.id != tenant.id,
                    TenantEntity.deleted_at.is_(None),
                )
            )
            if duplicate is not None:
                raise ValueError("This CNPJ is already assigned to another tenant")
            tenant.kind = "business"
            tenant.legal_name = legal_name
            tenant.registration_country = "BR"
            tenant.registration_type = "BR_CNPJ"
            tenant.registration_value_encrypted = encrypted
            tenant.registration_lookup_hmac = lookup
            tenant.registration_masked = masked
            tenant.registration_verification_status = "format_valid"
            tenant_changed = True
            tenant_service._audit(database, tenant.id, actor, "tenant.converted_to_business", {"registration_country": "BR", "registration_type": "BR_CNPJ", "registration_masked": masked, "verification_status": "format_valid", "migration": True})

        membership = database.scalar(
            select(TenantMemberEntity)
            .where(
                TenantMemberEntity.tenant_id == tenant.id,
                TenantMemberEntity.auth_user_id == member_email,
                TenantMemberEntity.deleted_at.is_(None),
            )
            .with_for_update()
        )
        member_changed = False
        if membership is None:
            active_members = database.scalars(
                select(TenantMemberEntity.id).where(
                    TenantMemberEntity.tenant_id == tenant.id,
                    TenantMemberEntity.status == "active",
                    TenantMemberEntity.deleted_at.is_(None),
                )
            ).all()
            if len(active_members) >= 3:
                raise ValueError("The tenant already has the Professional limit of 3 active members")
            database.add(TenantMemberEntity(tenant_id=tenant.id, auth_user_id=member_email, role="admin", status="active", joined_at=DateTimeService.utc_now()))
            member_changed = True
        elif membership.role != "admin" or membership.status != "active":
            membership.role = "admin"
            membership.status = "active"
            membership.joined_at = membership.joined_at or DateTimeService.utc_now()
            member_changed = True
        if member_changed:
            tenant_service._audit(database, tenant.id, actor, "tenant.member_migrated", {"member_role": "admin", "migration": True})

        return BusinessTenantMigrationResult(
            tenant_id=tenant.id,
            registration_masked=tenant.registration_masked or masked,
            tenant_changed=tenant_changed,
            member_changed=member_changed,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate an existing Rubrica tenant to a business tenant.")
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--member-email", required=True)
    parser.add_argument("--legal-name", required=True)
    parser.add_argument("--actor", required=True, help="Operator email recorded in the audit trail")
    args = parser.parse_args()
    try:
        cnpj = getpass("CNPJ (hidden): ")
        result = migrate_business_tenant(owner_email=args.owner_email, member_email=args.member_email, legal_name=args.legal_name, cnpj=cnpj, actor=args.actor)
    except (InvalidBusinessIdentifierError, ValueError, WorkflowError) as exc:
        parser.error(str(exc))
    print(f"[ok] tenant={result.tenant_id} cnpj={result.registration_masked} tenant_changed={result.tenant_changed} member_changed={result.member_changed}")


if __name__ == "__main__":
    main()
