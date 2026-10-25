"""Create development/staging fixtures without resetting existing scenarios."""

import os
from hashlib import sha256
from io import BytesIO
from uuid import UUID
from datetime import timedelta

from pypdf import PdfWriter
from sqlalchemy import MetaData, Table, func, inspect, select

from auth_api.infrastructure.database.connection import SessionLocal as AuthSessionLocal
from auth_api.modules.access_control.access_control_entity import UserRoleEntity
from auth_api.modules.users.passwords import hash_password
from auth_api.modules.users.user_entity import UserEntity
from auth_api.modules.users.user_identifier_entity import UserIdentifierEntity
from auth_api.modules.users.user_identifier_service import add_identifier
from core_api.infrastructure.auth_context import AuthContext, _active_auth_context
from core_api.infrastructure.database.connection import SessionLocal as CoreSessionLocal
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.document.document_entity import DocumentEntity
from core_api.modules.document.document_schema import DocumentCreate
from core_api.modules.signature_request.database_workflow_service import database_workflow_service
from core_api.modules.signature_request.signature_request_entity import SignatureRequestEntity, SignerEntity
from core_api.modules.signature_request.workflow_schema import SignatureRequestCreate
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_identity import protect_cnpj
from core_api.modules.tenant.tenant_schema import TenantProvision
from core_api.modules.tenant.tenant_service import _public_slug, tenant_service
from shared_kernel.time.datetime_service import DateTimeService


from toolbox.seeds.lifetime_account import change_lifetime_access
from toolbox.seeds.local_accounts_catalog import ACCOUNTS, LIFETIME, PROFESSIONAL, TEAM


def require_test_environment() -> str:
    environment = os.getenv("ENVIRONMENT", "").lower()
    expected_opt_in = {
        "local": "ALLOW_LOCAL_TEST_SEED",
        "development": "ALLOW_LOCAL_TEST_SEED",
        "staging": "ALLOW_STAGING_TEST_SEED",
    }.get(environment)
    if expected_opt_in is None:
        raise RuntimeError("Seed requires an explicit local/development/staging ENVIRONMENT")
    if os.getenv(expected_opt_in) != "1":
        raise RuntimeError(f"Seed requires {expected_opt_in}=1")
    from auth_api.infrastructure.settings import settings as auth_settings
    from core_api.infrastructure.settings import settings as core_settings
    if any(s.ENVIRONMENT.lower() != environment for s in (auth_settings, core_settings)):
        raise RuntimeError("Seed target does not match the application environment")
    return environment


def _auth_users(password: str) -> dict[str, UUID]:
    result: dict[str, UUID] = {}
    with AuthSessionLocal.begin() as database:
        for index, (email, name) in enumerate(ACCOUNTS, start=1):
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
            identifier = database.scalar(
                select(UserIdentifierEntity).where(
                    UserIdentifierEntity.user_id == user.id,
                    UserIdentifierEntity.identifier_type == "BR_CPF",
                    UserIdentifierEntity.issuing_country == "BR",
                )
            )
            if identifier is None:
                # Deterministic synthetic identifier used only by local/staging fixtures.
                base = f"{900_000_000 + index:09d}"
                digits = base
                for size in (9, 10):
                    total = sum(
                        int(digit) * weight
                        for digit, weight in zip(
                            digits[:size], range(size + 1, 1, -1), strict=True
                        )
                    )
                    digits += str((total * 10 % 11) % 10)
                add_identifier(
                    database,
                    user_id=user.id,
                    issuing_country="BR",
                    identifier_type="BR_CPF",
                    value=digits,
                )
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


def _expired_signature_request_fixture() -> None:
    """Create one immutable expired round for exercising the reopen workflow."""
    owner_email = "local.vitalicio.admin@example.local"
    title = "Contrato com prazo vencido"
    with CoreSessionLocal() as database:
        row = database.execute(
            select(TenantEntity, TenantMemberEntity)
            .join(TenantMemberEntity, TenantMemberEntity.tenant_id == TenantEntity.id)
            .where(
                TenantEntity.legal_name == "Conta Vitalícia Local Ltda.",
                TenantMemberEntity.auth_user_id == owner_email,
                TenantMemberEntity.role == "admin",
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("Lifetime fixture tenant was not created")
        tenant, member = row
        tenant_id, tenant_slug = tenant.id, tenant.slug
        owner_user_id = member.auth_user_uuid
        existing = database.scalar(
            select(DocumentEntity).where(
                DocumentEntity.tenant_id == tenant_id,
                DocumentEntity.title == title,
                DocumentEntity.created_by == owner_email,
                DocumentEntity.deleted_at.is_(None),
            )
        )
    if existing is not None:
        return

    previous_context = _active_auth_context.get()
    try:
        AuthContext(
            subject=owner_email,
            user_id=str(owner_user_id),
            email=owner_email,
            roles=frozenset({"user"}),
            permission_keys=frozenset(),
        )
        source = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_metadata({"/Title": title, "/Subject": "Fixture de solicitação vencida"})
        writer.write(source)
        document = database_workflow_service.create_document(
            DocumentCreate(
                organization_id=tenant_slug,
                title=title,
                original_filename="contrato-prazo-vencido.pdf",
                content_type="application/pdf",
                created_by=owner_email,
            ),
            source.getvalue(),
        )
        request = database_workflow_service.create_request(
            SignatureRequestCreate(
                document_id=document.id,
                expires_at=DateTimeService.utc_now() + timedelta(hours=1),
                created_by=owner_email,
            )
        )
    finally:
        _active_auth_context.set(previous_context)
    now = DateTimeService.utc_now()
    with CoreSessionLocal.begin() as database:
        entity = database.get(SignatureRequestEntity, request.id)
        entity.status = "open"
        entity.expires_at = now - timedelta(days=7)
        token = f"expired-fixture:{request.id}"
        database.add(
            SignerEntity(
                signature_request_id=request.id,
                auth_user_id=owner_email,
                name="Administrador Vitalício",
                email=owner_email,
                preferred_locale="pt-BR",
                signing_token_hash=sha256(token.encode()).hexdigest(),
                token_expires_at=entity.expires_at,
                status="pending",
                participant_role="company_representative",
                represented_tenant_id=tenant_id,
                representation_snapshot=entity.issuer_snapshot,
                signature_mode="serpro_timestamp",
            )
        )


def main() -> None:
    environment = require_test_environment()
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
    _expired_signature_request_fixture()
    print(
        f"[ok] {len(ACCOUNTS)} {environment} test accounts are ready "
        "(free, essential, professional 3, team 6, lifetime 3)"
    )
    for email, _ in ACCOUNTS:
        print(f"  {email}")


if __name__ == "__main__":
    main()
