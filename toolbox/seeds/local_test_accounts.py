"""Create local plan fixtures without resetting existing billing scenarios."""

import os
from uuid import UUID
from datetime import timedelta

from sqlalchemy import MetaData, Table, func, inspect, select

from auth_api.infrastructure.database.connection import SessionLocal as AuthSessionLocal
from auth_api.modules.access_control.access_control_entity import UserRoleEntity
from auth_api.modules.users.passwords import hash_password
from auth_api.modules.users.user_entity import UserEntity
from core_api.infrastructure.database.connection import SessionLocal as CoreSessionLocal
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_identity import protect_cnpj
from core_api.modules.tenant.tenant_schema import TenantProvision
from core_api.modules.tenant.tenant_service import _public_slug, tenant_service
from shared_kernel.time.datetime_service import DateTimeService


from toolbox.seeds.lifetime_account import change_lifetime_access
from toolbox.seeds.local_accounts_catalog import ACCOUNTS, LIFETIME, PROFESSIONAL, TEAM


def require_local_environment() -> None:
    if os.getenv("ENVIRONMENT", "").lower() not in {"local", "development"}:
        raise RuntimeError("Seed requires an explicit local/development ENVIRONMENT")
    if os.getenv("ALLOW_LOCAL_TEST_SEED") != "1":
        raise RuntimeError("Seed requires ALLOW_LOCAL_TEST_SEED=1")
    from auth_api.infrastructure.settings import settings as auth_settings
    from core_api.infrastructure.settings import settings as core_settings
    if any(s.ENVIRONMENT.lower() not in {"local", "development"} for s in (auth_settings, core_settings)):
        raise RuntimeError("Local test accounts cannot be created in production")


def _auth_users(password: str) -> dict[str, UUID]:
    result: dict[str, UUID] = {}
    with AuthSessionLocal.begin() as database:
        for email, name in ACCOUNTS:
            user = database.scalar(select(UserEntity).where(UserEntity.email == email))
            if user is None:
                user = UserEntity(email=email, name=name, password_hash=hash_password(password))
                database.add(user)
                database.flush()
            else:
                user.name = name
                user.password_hash = hash_password(password)
            user.email_verified = True
            user.is_active = True
            user.mfa_exempt = True
            user.mfa_enabled = False
            user.mfa_secret_ciphertext = None
            user.mfa_pending_secret_ciphertext = None
            user.mfa_last_used_step = None
            user.preferred_locale = "pt-BR"
            role = database.scalar(
                select(UserRoleEntity).where(
                    UserRoleEntity.user_id == user.id,
                    UserRoleEntity.role == "signature_admin",
                )
            )
            if role is None:
                database.add(UserRoleEntity(user_id=user.id, role="signature_admin"))
            result[email] = user.id
    return result


def _personal_tenants(users: dict[str, UUID]) -> None:
    for email, name in ACCOUNTS[:2]:
        tenant_service.provision_owner(
            TenantProvision(
                owner_user_id=users[email],
                owner_email=email,
                name=name,
                default_locale="pt-BR",
                country_code="BR",
            )
        )


def _set_plan(account: BillingAccountEntity, product: str) -> None:
    account.status = "active"
    account.provider = "fake"
    account.current_product_code = product
    account.complimentary_lifetime = False
    account.usage_period_starts_at = DateTimeService.utc_now()
    account.current_period_ends_at = DateTimeService.utc_now() + timedelta(days=30)


def _essential_plan(users: dict[str, UUID]) -> None:
    with CoreSessionLocal.begin() as database:
        account = database.scalar(
            select(BillingAccountEntity)
            .join(TenantMemberEntity, TenantMemberEntity.tenant_id == BillingAccountEntity.tenant_id)
            .where(TenantMemberEntity.auth_user_uuid == users["local.essencial@example.local"],
                   TenantMemberEntity.role == "admin")
        )
        # Only initialize once: rerunning the seed must preserve downgrade tests.
        if account.status == "not_configured" and account.provider is None:
            _set_plan(account, "rubrica_base")


def _business_tenant(users: dict[str, UUID], accounts, cnpj: str, name: str, product: str) -> None:
    encrypted, lookup, masked = protect_cnpj(cnpj)
    with CoreSessionLocal.begin() as database:
        tenant = database.scalar(
            select(TenantEntity).where(TenantEntity.registration_lookup_hmac == lookup)
        )
        if tenant is None:
            tenant = TenantEntity(
                name=name, slug=_public_slug(), kind="business", legal_name=name,
                registration_country="BR", registration_type="BR_CNPJ",
                registration_value_encrypted=encrypted, registration_lookup_hmac=lookup,
                registration_masked=masked, registration_verification_status="development_fixture",
                default_locale="pt-BR", country_code="BR", timezone="America/Sao_Paulo", currency="BRL",
            )
            database.add(tenant)
            database.flush()
            billing = BillingAccountEntity(tenant_id=tenant.id)
            _set_plan(billing, product)
            database.add(billing)
        else:
            if tenant.registration_verification_status != "development_fixture":
                raise RuntimeError("Refusing to modify a tenant not owned by the local seed")
            # Upgrade the original local fixture (previously lifetime) once.
            billing = database.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant.id))
            if (tenant.registration_verification_status == "development_fixture"
                    and billing.complimentary_lifetime and billing.provider is None):
                _set_plan(billing, product)
        for index, (email, _) in enumerate(accounts):
            membership = database.scalar(
                select(TenantMemberEntity).where(
                    TenantMemberEntity.tenant_id == tenant.id,
                    TenantMemberEntity.auth_user_uuid == users[email],
                )
            )
            if membership is None:
                database.add(TenantMemberEntity(
                    tenant_id=tenant.id, auth_user_id=email, auth_user_uuid=users[email],
                    role="admin" if index == 0 else "member", status="active",
                    joined_at=DateTimeService.utc_now(),
                ))


def _lifetime_tenant(users: dict[str, UUID]) -> None:
    cnpj = "45.723.174/0001-10"
    name = "Conta Vitalícia Local Ltda."
    encrypted, lookup, masked = protect_cnpj(cnpj)
    with CoreSessionLocal.begin() as database:
        tenant = database.scalar(
            select(TenantEntity).where(TenantEntity.registration_lookup_hmac == lookup)
        )
        if tenant is None:
            tenant = TenantEntity(
                name=name, slug=_public_slug(), kind="business", legal_name=name,
                registration_country="BR", registration_type="BR_CNPJ",
                registration_value_encrypted=encrypted, registration_lookup_hmac=lookup,
                registration_masked=masked, registration_verification_status="development_fixture",
                default_locale="pt-BR", country_code="BR", timezone="America/Sao_Paulo", currency="BRL",
            )
            database.add(tenant)
            database.flush()
            database.add(BillingAccountEntity(tenant_id=tenant.id, status="not_configured"))
        elif tenant.registration_verification_status != "development_fixture":
            raise RuntimeError("Refusing to modify a tenant not owned by the local seed")
        for index, (email, _) in enumerate(LIFETIME):
            membership = database.scalar(select(TenantMemberEntity).where(
                TenantMemberEntity.tenant_id == tenant.id,
                TenantMemberEntity.auth_user_uuid == users[email],
            ))
            if membership is None:
                database.add(TenantMemberEntity(
                    tenant_id=tenant.id, auth_user_id=email, auth_user_uuid=users[email],
                    role="admin" if index == 0 else "member", status="active",
                    joined_at=DateTimeService.utc_now(),
                ))
        tenant_id = tenant.id
    change_lifetime_access(
        tenant_id,
        enabled=True,
        actor="local-seed@rubrica.invalid",
        reason="Local development fixture",
    )


def _archive_empty_legacy_personal_tenants(users: dict[str, UUID]) -> None:
    """Retire only unused personal workspaces created by the older local seed."""
    with CoreSessionLocal.begin() as db:
        connection = db.connection()
        inspector = inspect(connection)
        references = []
        for table_name in inspector.get_table_names():
            if table_name in {"tenant_members", "billing_accounts"}:
                continue
            for fk in inspector.get_foreign_keys(table_name):
                if fk["referred_table"] == "tenants":
                    table = Table(table_name, MetaData(), autoload_with=connection)
                    references.extend(table.c[column] for column in fk["constrained_columns"])
        for email, name in (*PROFESSIONAL, *TEAM):
            tenants = db.scalars(select(TenantEntity).join(TenantMemberEntity).where(
                TenantEntity.kind == "personal", TenantEntity.name == name,
                TenantEntity.deleted_at.is_(None),
                TenantMemberEntity.auth_user_uuid == users[email],
                TenantMemberEntity.role == "admin",
            )).all()
            for tenant in tenants:
                billing = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant.id))
                members = db.scalars(select(TenantMemberEntity).where(TenantMemberEntity.tenant_id == tenant.id)).all()
                if len(members) != 1 or billing is None:
                    continue
                if (billing.provider or billing.status != "not_configured" or billing.complimentary_lifetime
                        or billing.signatures_used or billing.files_uploaded_in_period):
                    continue
                if any(db.scalar(select(func.count()).select_from(column.table).where(column == tenant.id))
                       for column in references):
                    continue
                now = DateTimeService.utc_now()
                tenant.deleted_at = now
                tenant.status = "archived"
                members[0].deleted_at = now
                members[0].status = "inactive"
                billing.deleted_at = now


def main() -> None:
    require_local_environment()
    password = os.getenv("LOCAL_TEST_ACCOUNT_PASSWORD", "RubricaLocal123!")
    if len(password) < 12:
        raise ValueError("LOCAL_TEST_ACCOUNT_PASSWORD must contain at least 12 characters")
    users = _auth_users(password)
    _personal_tenants(users)
    _essential_plan(users)
    _business_tenant(users, PROFESSIONAL, "11.444.777/0001-61", "Empresa Local de Testes Ltda.", "rubrica_intermediate")
    _business_tenant(users, TEAM, "11.222.333/0001-81", "Equipe Local de Testes Ltda.", "rubrica_team")
    _lifetime_tenant(users)
    _archive_empty_legacy_personal_tenants(users)
    print(f"[ok] {len(ACCOUNTS)} local test accounts are ready (free, essential, professional 3, team 6, lifetime 3)")
    for email, _ in ACCOUNTS:
        print(f"  {email}")


if __name__ == "__main__":
    main()
