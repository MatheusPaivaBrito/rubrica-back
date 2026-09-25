"""Create the three deterministic accounts used only by local development."""

import os
from uuid import UUID

from sqlalchemy import select

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


ACCOUNTS = (
    ("local.pessoal@example.local", "Conta Pessoal Local"),
    ("local.empresa.admin@example.local", "Administrador Empresa Local"),
    ("local.empresa.membro@example.local", "Membro Empresa Local"),
)


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
    for email, name in ACCOUNTS:
        tenant_service.provision_owner(
            TenantProvision(
                owner_user_id=users[email],
                owner_email=email,
                name=name,
                default_locale="pt-BR",
                country_code="BR",
            )
        )


def _business_tenant(users: dict[str, UUID]) -> None:
    admin_email = ACCOUNTS[1][0]
    member_email = ACCOUNTS[2][0]
    encrypted, lookup, masked = protect_cnpj("11.444.777/0001-61")
    with CoreSessionLocal.begin() as database:
        tenant = database.scalar(
            select(TenantEntity).where(TenantEntity.registration_lookup_hmac == lookup)
        )
        if tenant is None:
            tenant = TenantEntity(
                name="Empresa Local de Testes Ltda.",
                slug=_public_slug(),
                kind="business",
                legal_name="Empresa Local de Testes Ltda.",
                registration_country="BR",
                registration_type="BR_CNPJ",
                registration_value_encrypted=encrypted,
                registration_lookup_hmac=lookup,
                registration_masked=masked,
                registration_verification_status="development_fixture",
                default_locale="pt-BR",
                country_code="BR",
                timezone="America/Sao_Paulo",
                currency="BRL",
            )
            database.add(tenant)
            database.flush()
            database.add(
                BillingAccountEntity(
                    tenant_id=tenant.id,
                    status="active",
                    complimentary_lifetime=True,
                )
            )
        for email, role in ((admin_email, "admin"), (member_email, "member")):
            membership = database.scalar(
                select(TenantMemberEntity).where(
                    TenantMemberEntity.tenant_id == tenant.id,
                    TenantMemberEntity.auth_user_uuid == users[email],
                    TenantMemberEntity.deleted_at.is_(None),
                )
            )
            if membership is None:
                database.add(
                    TenantMemberEntity(
                        tenant_id=tenant.id,
                        auth_user_id=email,
                        auth_user_uuid=users[email],
                        role=role,
                        status="active",
                        joined_at=DateTimeService.utc_now(),
                    )
                )


def main() -> None:
    if os.getenv("ENVIRONMENT", "development").lower() in {"production", "prod"}:
        raise RuntimeError("Local test accounts cannot be created in production")
    password = os.getenv("LOCAL_TEST_ACCOUNT_PASSWORD", "RubricaLocal123!")
    if len(password) < 12:
        raise ValueError("LOCAL_TEST_ACCOUNT_PASSWORD must contain at least 12 characters")
    users = _auth_users(password)
    _personal_tenants(users)
    _business_tenant(users)
    print("[ok] three local test accounts are ready")
    for email, _ in ACCOUNTS:
        print(f"  {email}")


if __name__ == "__main__":
    main()
