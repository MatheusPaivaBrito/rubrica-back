"""Isolated workspace fixtures used by the staging manual test matrix."""

from datetime import timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from auth_api.modules.users.user_entity import UserEntity
from auth_api.modules.users.user_identifier_entity import UserIdentifierEntity
from auth_api.modules.users.user_identifier_service import add_identifier
from core_api.infrastructure.auth_context import AuthContext, _active_auth_context
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.document.document_entity import DocumentEntity
from core_api.modules.document.document_schema import DocumentCreate
from core_api.modules.signature_request.database_workflow_service import database_workflow_service
from core_api.modules.signature_request.signature_request_entity import SignatureRequestEntity, SignerEntity
from core_api.modules.signature_request.workflow_schema import SignatureRequestCreate
from core_api.modules.tenant.business_upgrade_review import BusinessUpgradeReviewEntity
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_identity import protect_cnpj
from core_api.modules.tenant.tenant_schema import TenantProvision
from shared_kernel.time.datetime_service import DateTimeService
from toolbox.seeds.local_accounts_catalog import staging_email
from toolbox.seeds.local_test_accounts import AuthSessionLocal, CoreSessionLocal, _set_plan, require_test_environment, tenant_service
from toolbox.seeds.scenario_pdf import scenario_pdf


def _fixture_cnpj(index: int) -> str:
    digits = f"97{index:06d}0001"
    for weights in ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)):
        remainder = sum(int(digit) * weight for digit, weight in zip(digits, weights, strict=True)) % 11
        digits += str(0 if remainder < 2 else 11 - remainder)
    return digits


def _business(db, key: str, index: int, parent_id: UUID | None = None) -> TenantEntity:
    slug = f"staging-cenario-{key}"
    tenant = db.scalar(select(TenantEntity).where(TenantEntity.slug == slug))
    if tenant is not None:
        if tenant.registration_source != "staging_scenario":
            raise RuntimeError("Refusing to update a workspace outside the staging scenario seed")
        return tenant
    encrypted, lookup, masked = protect_cnpj(_fixture_cnpj(index))
    name = f"Cenário staging · {key}"
    tenant = TenantEntity(
        slug=slug, name=name, legal_name=name, kind="business", default_locale="pt-BR",
        country_code="BR", currency="BRL", timezone="America/Sao_Paulo", parent_workspace_id=parent_id,
        registration_country="BR", registration_type="BR_CNPJ", registration_value_encrypted=encrypted,
        registration_lookup_hmac=lookup, registration_masked=masked,
        registration_source="staging_scenario", registration_verification_status="development_fixture",
    )
    db.add(tenant)
    db.flush()
    billing = BillingAccountEntity(tenant_id=tenant.id)
    _set_plan(billing, "rubrica_team")
    db.add(billing)
    return tenant


def _member(db, tenant, users, key, *, role="member", status="active", scope="own", company_only=False):
    email = staging_email(key)
    if db.scalar(select(TenantMemberEntity.id).where(
        TenantMemberEntity.tenant_id == tenant.id, TenantMemberEntity.auth_user_uuid == users[email],
    )) is None:
        db.add(TenantMemberEntity(
            tenant_id=tenant.id, auth_user_id=email, auth_user_uuid=users[email], role=role,
            status=status, document_scope=scope, sign_company_only=company_only,
            joined_at=DateTimeService.utc_now() - timedelta(days=5),
        ))


def _pdf(tenant_id, owner_key, users, title, *, days=0, open_request=False):
    email = staging_email(owner_key)
    with CoreSessionLocal() as db:
        tenant = db.get(TenantEntity, tenant_id)
        existing = db.scalar(select(DocumentEntity.id).where(
            DocumentEntity.tenant_id == tenant_id, DocumentEntity.title == title,
            DocumentEntity.deleted_at.is_(None),
        ))
        if existing is not None or tenant.workspace_closed_at is not None:
            return
        slug = tenant.slug

    context = _active_auth_context.get()
    try:
        AuthContext(subject=email, user_id=str(users[email]), email=email, roles=frozenset(), permission_keys=frozenset())
        document = database_workflow_service.create_document(DocumentCreate(
            organization_id=slug, title=title, original_filename=f"{title}.pdf",
            content_type="application/pdf", created_by=email,
        ), scenario_pdf(title))
        request = None
        if open_request:
            request = database_workflow_service.create_request(SignatureRequestCreate(
                document_id=document.id, expires_at=DateTimeService.utc_now() + timedelta(days=90),
                created_by=email,
            ))
    finally:
        _active_auth_context.set(context)
    with CoreSessionLocal.begin() as db:
        if days:
            db.get(DocumentEntity, document.id).created_at = DateTimeService.utc_now() - timedelta(days=days)
        if request:
            entity = db.get(SignatureRequestEntity, request.id)
            entity.status = "open"
            entity.opened_at = DateTimeService.utc_now()
            db.add(SignerEntity(
                signature_request_id=request.id, auth_user_id=email, email=email, name="Signatário de staging",
                preferred_locale="pt-BR", status="pending", participant_role="personal_signer",
                signature_mode="evidence", token_expires_at=entity.expires_at,
                signing_token_hash=sha256(f"staging-scenario:{request.id}".encode()).hexdigest(),
            ))


def seed_scenarios(users: dict[str, UUID]) -> None:
    if require_test_environment() != "staging":
        raise RuntimeError("Workspace scenario fixtures are exclusive to staging")

    personal = {}
    for key in (
        "ex-membro-com-pessoal", "outra-empresa", "tres-workspaces", "franquia-esgotada",
        "assina-pela-empresa", "identidades", "checkout", "upgrade-empresa",
    ):
        email = staging_email(key)
        personal[key] = tenant_service.provision_owner(TenantProvision(
            owner_user_id=users[email], owner_email=email, name=f"Pessoal · {key}",
            default_locale="pt-BR", country_code="BR",
        )).id

    with AuthSessionLocal.begin() as db:
        user = db.get(UserEntity, users[staging_email("identidades")])
        identifiers = db.scalars(select(UserIdentifierEntity).where(UserIdentifierEntity.user_id == user.id)).all()
        if not any(item.issuing_country == "JP" and item.identifier_type == "PASSPORT" for item in identifiers):
            add_identifier(db, user_id=user.id, issuing_country="JP", identifier_type="PASSPORT", value="RUBRICATESTJP2026")
        if user.preferred_identifier_id is None:
            user.preferred_identifier_id = next(item.id for item in identifiers if item.identifier_type == "BR_CPF")

    with CoreSessionLocal.begin() as db:
        headquarters = _business(db, "sede", 1)
        workspace_a = _business(db, "filial-a", 2, headquarters.id)
        workspace_b = _business(db, "filial-b", 3, headquarters.id)
        history = _business(db, "historico", 4)
        closing = _business(db, "encerramento", 5)
        export = _business(db, "exportacao-aberta", 6)
        expired = _business(db, "exportacao-vencida", 7)
        access = _business(db, "permissoes", 8)
        membership = _business(db, "vinculos", 9)
        for tenant, key in (
            (headquarters, "admin-sede"), (workspace_a, "gestor-filial"), (history, "admin-sede"),
            (closing, "encerramento"), (export, "exportacao-aberta"), (expired, "exportacao-vencida"),
            (access, "admin-sede"), (membership, "admin-sede"),
        ):
            _member(db, tenant, users, key, role="admin")

        for key, status in (
            ("ex-membro-sem-pessoal", "offboarded"), ("suspenso-sem-pessoal", "suspended"),
            ("sem-assento-sem-pessoal", "without_seat"), ("ex-membro-com-pessoal", "offboarded"),
            ("virada-ciclo", "active"),
        ):
            _member(db, membership, users, key, status=status)
        for key, scope in (("arquivos-proprios", "own"), ("arquivos-desde-entrada", "since_joined"), ("arquivos-todos", "all")):
            _member(db, access, users, key, scope=scope)
        _member(db, access, users, "assina-pela-empresa", company_only=True)
        for key in ("readmitir-restaurar", "readmitir-novo"):
            _member(db, history, users, key, status="offboarded")
        _member(db, headquarters, users, "admin-sucessor")
        _member(db, workspace_a, users, "auditor-filial", role="auditor")
        _member(db, workspace_a, users, "membro-filial")
        _member(db, workspace_a, users, "outra-empresa", status="offboarded")
        _member(db, workspace_b, users, "outra-empresa")
        for tenant in (workspace_a, workspace_b):
            _member(db, tenant, users, "tres-workspaces")
        _member(db, workspace_b, users, "franquia-esgotada")

        billing = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == personal["franquia-esgotada"]))
        if billing.status == "not_configured":
            billing.signatures_used = billing.free_signatures_limit

        for index, (label, status, branch) in enumerate((
            ("Filial A de staging", "approved", workspace_a),
            ("Filial B de staging", "approved", workspace_b),
            ("Filial aguardando revisão", "pending", None),
            ("Filial com CNPJ rejeitado", "rejected", None),
            ("Filial aguardando pagamento", "approved", None),
        ), start=2):
            cnpj_index = index if index < 4 else index + 10
            encrypted, lookup, masked = protect_cnpj(_fixture_cnpj(cnpj_index))
            if db.scalar(select(BusinessUpgradeReviewEntity.id).where(
                BusinessUpgradeReviewEntity.tenant_id == headquarters.id,
                BusinessUpgradeReviewEntity.cnpj_lookup == lookup,
            )) is None:
                db.add(BusinessUpgradeReviewEntity(
                    tenant_id=headquarters.id, is_branch=True, business_tenant_id=branch.id if branch else None,
                    requested_by=staging_email("admin-sede"), legal_name=label, cnpj_encrypted=encrypted,
                    cnpj_lookup=lookup, cnpj_masked=masked, status=status,
                ))
        ids = [tenant.id for tenant in (workspace_a, workspace_b, history, closing, export, expired, access, membership)]

    a_id, b_id, history_id, closing_id, export_id, expired_id, access_id, membership_id = ids
    # All uploads use the normal storage and encryption paths. No Stripe or Resend calls.
    for key in ("ex-membro-com-pessoal", "outra-empresa", "tres-workspaces", "upgrade-empresa", "identidades"):
        _pdf(personal[key], key, users, "PDF pessoal de teste", open_request=key == "identidades")
    _pdf(a_id, "gestor-filial", users, "PDF exclusivo da filial A")
    _pdf(b_id, "admin-sede", users, "PDF exclusivo da filial B")
    _pdf(access_id, "admin-sede", users, "PDF anterior à admissão", days=10)
    _pdf(access_id, "admin-sede", users, "PDF posterior à admissão")
    _pdf(access_id, "arquivos-proprios", users, "PDF do próprio membro")
    _pdf(membership_id, "admin-sede", users, "PDF do vínculo empresarial")
    for key in ("readmitir-restaurar", "readmitir-novo"):
        title = f"PDF antigo · {key}"
        _pdf(history_id, "admin-sede", users, title, days=3)
        with CoreSessionLocal.begin() as db:
            document = db.scalar(select(DocumentEntity).where(
                DocumentEntity.tenant_id == history_id, DocumentEntity.title == title,
            ))
            if document is not None and document.created_by == staging_email("admin-sede"):
                document.created_by = staging_email(key)
    _pdf(closing_id, "encerramento", users, "PDF com solicitação em aberto", open_request=True)
    for tenant_id, key, days in ((export_id, "exportacao-aberta", 2), (expired_id, "exportacao-vencida", 31)):
        _pdf(tenant_id, key, users, "PDF do acervo encerrado")
        with CoreSessionLocal.begin() as db:
            tenant = db.get(TenantEntity, tenant_id)
            if tenant.workspace_closed_at is None:
                tenant.workspace_closed_at = DateTimeService.utc_now() - timedelta(days=days)
                tenant.closure_requested_at = tenant.workspace_closed_at
