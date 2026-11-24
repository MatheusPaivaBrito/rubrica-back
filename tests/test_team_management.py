from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core_api.infrastructure.auth_context import AuthContext, _active_auth_context
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.document.document_entity import DocumentEntity, DocumentVersionEntity
from core_api.modules.signature_request.database_workflow_service import DatabaseSignatureWorkflowService
from core_api.modules.signature_request.signature_request_entity import AuditEventEntity, SignatureRequestEntity, SignerEntity
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant import tenant_service as module
from core_api.modules.tenant.tenant_entity import (
    TenantEntity,
    TenantMemberEntity,
    TenantSeatRosterEntity,
)
from core_api.modules.tenant.tenant_schema import (
    TenantCreate,
    TenantMemberInvitation,
    TenantSeatRosterUpdate,
    TenantTeamUpdate,
)
from shared_kernel.time.datetime_service import DateTimeService
from toolbox.operations import staging_billing


@pytest.fixture
def team_db(monkeypatch):
    token = _active_auth_context.set(None)
    engine = create_engine('sqlite://')
    for entity in (
        TenantEntity,
        TenantMemberEntity,
        TenantSeatRosterEntity,
        BillingAccountEntity,
        AuditEventEntity,
        DocumentEntity,
        DocumentVersionEntity,
        SignatureRequestEntity,
        SignerEntity,
    ):
        entity.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(module, 'SessionLocal', factory)
    with factory.begin() as db:
        tenant = TenantEntity(name='Team', slug='team-test', kind='business')
        db.add(tenant)
        db.flush()
        db.add(BillingAccountEntity(tenant_id=tenant.id, status='active', current_product_code='rubrica_team'))
        members = [TenantMemberEntity(tenant_id=tenant.id, auth_user_id=f'member{i}@example.local',
                   role='admin' if i == 0 else 'member', status='active') for i in range(6)]
        db.add_all(members)
        db.flush()
        tenant_id, member_ids = tenant.id, [m.id for m in members]
    yield factory, tenant_id, member_ids
    _active_auth_context.reset(token)


def test_downgrade_requires_selection_then_revokes_only_suspended_members(team_db):
    factory, tenant_id, ids = team_db
    service = module.tenant_service
    assert service.team(tenant_id, 'member0@example.local').member_limit == 10
    with factory.begin() as db:
        db.scalar(select(BillingAccountEntity)).current_product_code = 'rubrica_intermediate'
    state = service.team(tenant_id, 'member0@example.local')
    assert state.member_limit == 3 and state.requires_selection
    with factory() as db, pytest.raises(WorkflowError):
        service.require_role(db, tenant_id, 'member1@example.local')
    result = service.update_team(tenant_id, TenantTeamUpdate(active_member_ids=ids[:3]), 'member0@example.local')
    assert result.active_count == 3 and not result.requires_selection
    assert [m.status for m in result.members].count('suspended') == 3
    assert service.list_for('member4@example.local') == []
    with factory() as db:
        service.require_role(db, tenant_id, 'member1@example.local')
        with pytest.raises(WorkflowError):
            service.require_role(db, tenant_id, 'member4@example.local')
        assert db.scalar(select(AuditEventEntity)).action == 'tenant.team_updated'
    with factory.begin() as db:
        db.scalar(select(BillingAccountEntity)).current_product_code = 'rubrica_team'
    assert service.update_team(tenant_id, TenantTeamUpdate(active_member_ids=ids), 'member0@example.local').active_count == 6


def test_downgrade_to_essential_automatically_keeps_only_administrator(team_db):
    factory, tenant_id, _ = team_db
    with factory.begin() as db:
        db.scalar(select(BillingAccountEntity)).current_product_code = 'rubrica_base'

    state = module.tenant_service.team(tenant_id, 'member0@example.local')

    assert state.member_limit == 1
    assert state.active_count == 1
    assert not state.requires_selection
    assert [member.auth_user_id for member in state.members if member.status == 'active'] == [
        'member0@example.local'
    ]
    with factory() as db:
        audit = db.scalar(
            select(AuditEventEntity).where(
                AuditEventEntity.action == 'tenant.team_reconciled_after_downgrade'
            )
        )
        assert audit is not None


def test_suspended_member_can_create_personal_workspace_without_restoring_business_access(team_db):
    factory, tenant_id, _ = team_db
    with factory.begin() as db:
        db.scalar(select(BillingAccountEntity)).current_product_code = 'rubrica_base'
    module.tenant_service.team(tenant_id, 'member0@example.local')

    state = module.tenant_service.access_state('member1@example.local')
    assert state.active_tenant_count == 0
    assert state.can_create_personal_tenant
    assert [item.tenant_id for item in state.suspended_tenants] == [tenant_id]

    personal = module.tenant_service.create_personal_after_suspension(
        TenantCreate(name='Member 1', default_locale='pt-BR', country_code='BR', currency='BRL'),
        'member1@example.local',
        None,
    )

    assert personal.kind == 'personal'
    assert [tenant.id for tenant in module.tenant_service.list_for('member1@example.local')] == [personal.id]
    with factory() as db:
        old_membership = db.scalar(select(TenantMemberEntity).where(
            TenantMemberEntity.tenant_id == tenant_id,
            TenantMemberEntity.auth_user_id == 'member1@example.local',
        ))
        assert old_membership.status == 'suspended'


def test_personal_reactivation_recovers_account_with_no_workspace(team_db):
    service = module.tenant_service
    business_member = "member0@example.local"
    assert service.access_state(business_member).can_create_personal_tenant
    personal = service.create_personal_after_suspension(
        TenantCreate(name="Personal", country_code="BR"), business_member, None
    )
    assert personal.kind == "personal"
    assert not service.access_state(business_member).can_create_personal_tenant
    assert {workspace.kind for workspace in service.list_for(business_member)} == {"business", "personal"}
    subject = "outsider@example.local"
    assert service.access_state(subject).can_create_personal_tenant
    with pytest.raises(WorkflowError, match="Choose the country"):
        service.create_personal_after_suspension(TenantCreate(name="Outsider"), subject, None)
    payload = TenantCreate(name="Outsider", country_code="JP", currency="USD")
    personal = service.create_personal_after_suspension(payload, subject, None)
    assert personal.currency == "JPY"
    assert service.create_personal_after_suspension(payload, subject, None).id == personal.id
    assert [tenant.id for tenant in service.list_for(subject)] == [personal.id]


@pytest.mark.parametrize('selection', ['over_limit', 'without_admin', 'foreign'])
def test_rejected_selection_is_atomic(team_db, selection):
    factory, tenant_id, ids = team_db
    with factory.begin() as db:
        db.scalar(select(BillingAccountEntity)).current_product_code = 'rubrica_intermediate'
    selected = {'over_limit': ids[:4], 'without_admin': ids[1:3], 'foreign': [ids[0], uuid4()]}[selection]
    with pytest.raises(WorkflowError):
        module.tenant_service.update_team(tenant_id, TenantTeamUpdate(active_member_ids=selected), 'member0@example.local')
    assert module.tenant_service.team(tenant_id, 'member0@example.local').active_count == 6


def test_member_cannot_manage_and_cross_tenant_access_is_denied(team_db):
    _, tenant_id, ids = team_db
    service = module.tenant_service
    with pytest.raises(WorkflowError):
        service.team(tenant_id, 'member1@example.local')
    with pytest.raises(WorkflowError):
        service.update_team(tenant_id, TenantTeamUpdate(active_member_ids=ids[:3]), 'member1@example.local')
    with pytest.raises(WorkflowError):
        service.team(tenant_id, 'outsider@example.local')
    with pytest.raises(WorkflowError):
        service.update_team(uuid4(), TenantTeamUpdate(active_member_ids=ids[:3]), 'member0@example.local')


def test_stable_auth_identity_survives_email_change(team_db):
    factory, tenant_id, ids = team_db
    user_id = uuid4()
    with factory.begin() as db:
        db.get(TenantMemberEntity, ids[0]).auth_user_uuid = user_id
    AuthContext(subject='new-email@example.local', user_id=str(user_id), roles=frozenset(), permission_keys=frozenset())
    state = module.tenant_service.team(tenant_id, 'new-email@example.local')
    assert state.can_manage and state.current_member_id == ids[0]


@pytest.mark.parametrize('product,status,expected', [('rubrica_base','active',1), ('rubrica_team','cancelled',1), ('rubrica_intermediate','active',3)])
def test_team_limit_uses_current_entitlement(team_db, product, status, expected):
    factory, tenant_id, _ = team_db
    with factory.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        account.current_product_code = product
        account.status = status
    assert module.tenant_service.team(tenant_id, 'member0@example.local').member_limit == expected


def test_complimentary_lifetime_tenant_has_ten_members(team_db):
    factory, tenant_id, ids = team_db
    with factory.begin() as db:
        db.scalar(select(BillingAccountEntity)).complimentary_lifetime = True

    state = module.tenant_service.team(tenant_id, 'member0@example.local')

    assert state.member_limit == 10
    assert state.active_count == 6
    assert not state.requires_selection
    updated = module.tenant_service.update_team(
        tenant_id,
        TenantTeamUpdate(active_member_ids=ids),
        'member0@example.local',
    )
    assert updated.active_count == 6


def test_next_cycle_roster_does_not_change_current_occupants_until_cutover(team_db):
    factory, tenant_id, ids = team_db
    cycle_start = DateTimeService.utc_now() + timedelta(days=5)
    with factory.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        account.current_product_code = 'rubrica_intermediate'
        account.contracted_seats = 3
        account.current_period_ends_at = cycle_start

    scheduled = module.tenant_service.schedule_seat_roster(
        tenant_id,
        TenantSeatRosterUpdate(member_ids=[ids[0], ids[4], ids[5]]),
        'member0@example.local',
    )

    assert scheduled.active_count == 6
    assert set(scheduled.next_cycle_member_ids) == {ids[0], ids[4], ids[5]}
    with factory.begin() as db:
        roster = db.scalar(select(TenantSeatRosterEntity))
        roster.cycle_starts_at = DateTimeService.utc_now() - timedelta(seconds=1)
        module.tenant_service.apply_due_seat_roster(db, tenant_id)

    applied = module.tenant_service.team(tenant_id, 'member0@example.local')
    assert applied.active_count == 3
    assert set(applied.current_seat_member_ids) == {ids[0], ids[4], ids[5]}
    assert [member.status for member in applied.members].count('without_seat') == 3


def test_professional_personal_tenant_can_invite_member(team_db, monkeypatch):
    factory, tenant_id, _ = team_db
    invited_user_id = uuid4()
    with factory.begin() as db:
        tenant = db.get(TenantEntity, tenant_id)
        tenant.kind = 'personal'
        account = db.scalar(select(BillingAccountEntity))
        account.current_product_code = 'rubrica_intermediate'
        db.query(TenantMemberEntity).filter(
            TenantMemberEntity.role != 'admin'
        ).delete(synchronize_session=False)
    monkeypatch.setattr(module, 'invite_auth_user', lambda **_kwargs: invited_user_id)

    module.tenant_service.invite_member(
        tenant_id,
        TenantMemberInvitation(
            name='New Member',
            email='new.member@example.local',
            document='12345678909',
        ),
        'member0@example.local',
    )

    state = module.tenant_service.team(tenant_id, 'member0@example.local')
    assert state.member_limit == 3
    assert state.active_count == 2
    with factory() as db:
        invited = db.scalar(select(TenantMemberEntity).where(
            TenantMemberEntity.auth_user_id == 'new.member@example.local'
        ))
        assert invited is not None
        assert invited.auth_user_uuid == invited_user_id


def test_admin_can_change_member_role_and_change_is_audited(team_db):
    factory, tenant_id, ids = team_db

    state = module.tenant_service.update_member_role(
        tenant_id, ids[1], 'auditor', 'member0@example.local'
    )

    assert next(member for member in state.members if member.id == ids[1]).role == 'auditor'
    with factory() as db:
        audit = db.scalars(
            select(AuditEventEntity).where(
                AuditEventEntity.action == 'tenant.member_role_updated'
            )
        ).one()
        assert audit.metadata_sanitized['role'] == 'auditor'


def test_admin_cannot_change_own_role(team_db):
    _, tenant_id, ids = team_db
    with pytest.raises(WorkflowError):
        module.tenant_service.update_member_role(
            tenant_id, ids[0], 'member', 'member0@example.local'
        )

def test_staging_shortcut_applies_future_seats_without_moving_billing_cycle(team_db):
    factory, tenant_id, ids = team_db
    cycle_start = DateTimeService.utc_now() + timedelta(days=5)
    with factory.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        account.current_period_ends_at = cycle_start

    module.tenant_service.schedule_seat_roster(
        tenant_id, TenantSeatRosterUpdate(member_ids=ids[:5]), "member0@example.local"
    )
    with factory.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        staging_billing.apply_cycle(db, account)

    with factory() as db:
        account = db.scalar(select(BillingAccountEntity))
        roster = db.scalar(select(TenantSeatRosterEntity))
        assert account.current_period_ends_at == cycle_start.replace(tzinfo=None)
        assert roster.status == "applied"
        assert roster.applied_at < roster.cycle_starts_at
        assert db.get(TenantMemberEntity, ids[-1]).status == "without_seat"


def test_staging_shortcut_sets_plan_without_stripe_and_rejects_linked_account(team_db):
    factory, tenant_id, ids = team_db
    with factory.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        staging_billing.set_test_plan(db, account, staging_billing.ESSENTIAL)
        assert account.provider == "fake"
        assert account.current_product_code == staging_billing.ESSENTIAL
        assert account.contracted_seats == 1
        assert db.get(TenantMemberEntity, ids[-1]).status == "suspended"
        account.provider_customer_id = "cus_test"

    with factory.begin() as db:
        account = db.scalar(select(BillingAccountEntity))
        with pytest.raises(SystemExit, match="vínculo Stripe"):
            staging_billing.set_test_plan(db, account, staging_billing.TEAM)
        assert account.current_product_code == staging_billing.ESSENTIAL


def test_staging_billing_refuses_production_before_opening_database(monkeypatch):
    import sys

    def unexpected_database():
        pytest.fail("Must refuse production before opening a database session")

    monkeypatch.setattr(sys, "argv", ["staging_billing", "staging-set-test-plan"])
    monkeypatch.setattr(staging_billing.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(staging_billing, "SessionLocal", unexpected_database)
    with pytest.raises(SystemExit, match="exclusiva de staging"):
        staging_billing.main()


def test_only_active_plan_workspaces_are_selectable(team_db):
    factory, tenant_id, _ = team_db
    with factory.begin() as db:
        personal = TenantEntity(name="Personal", slug="me-test", kind="personal", status="active")
        db.add(personal)
        db.flush()
        db.add(TenantMemberEntity(
            tenant_id=personal.id, auth_user_id="member0@example.local",
            role="admin", status="active",
        ))
        db.get(TenantEntity, tenant_id).status = "active"

    workspaces = module.tenant_service.list_for("member0@example.local")
    assert {space.kind for space in workspaces if space.workspace_selectable} == {"personal", "business"}

    with factory.begin() as db:
        db.scalar(select(BillingAccountEntity)).status = "cancelled"

    workspaces = module.tenant_service.list_for("member0@example.local")
    assert [space.kind for space in workspaces if space.workspace_selectable] == ["personal"]

def test_document_scope_updates_listing_and_direct_access(team_db, monkeypatch):
    from core_api.modules.signature_request import database_workflow_service as workflow

    factory, tenant_id, ids = team_db
    monkeypatch.setattr(workflow, "SessionLocal", factory)
    service = DatabaseSignatureWorkflowService(None)
    now = DateTimeService.utc_now()
    member = "member1@example.local"
    admin = "member0@example.local"
    with factory.begin() as db:
        db.get(TenantMemberEntity, ids[1]).joined_at = now
        documents = []
        for title, author, created_at in (
            ("Own", member, now + timedelta(seconds=1)),
            ("Earlier", admin, now - timedelta(days=1)),
            ("Later", admin, now + timedelta(seconds=1)),
        ):
            record = DocumentEntity(
                tenant_id=tenant_id, organization_id="team-test", title=title,
                original_filename=f"{title}.pdf", content_type="application/pdf",
                storage_key=title, sha256="f" * 64, version=1, status="ready",
                created_by=author, created_at=created_at,
            )
            db.add(record)
            documents.append(record)
        db.flush()
        ids_by_title = {record.title: record.id for record in documents}

    assert {record.title for record in service.list_documents(member)} == {"Own"}
    for scope, expected in (
        ("all", {"Own", "Earlier", "Later"}),
        ("since_joined", {"Own", "Later"}),
        ("own", {"Own"}),
    ):
        module.tenant_service.update_document_scope(tenant_id, ids[1], scope, admin)
        assert {record.title for record in service.list_documents(member)} == expected
        assert {record.title for record in service.list_documents(admin)} == set(ids_by_title)
        for title, document_id in ids_by_title.items():
            if title in expected:
                assert service.get_document(str(document_id), member).title == title
            else:
                with pytest.raises(WorkflowError, match="Document access is not allowed"):
                    service.get_document(str(document_id), member)
    with pytest.raises(WorkflowError, match="Tenant access denied"):
        module.tenant_service.update_document_scope(tenant_id, ids[1], "all", member)


def test_business_review_does_not_convert_or_activate_personal_workspace(team_db, monkeypatch):
    from core_api.modules.tenant import business_upgrade_review as review
    from core_api.modules.tenant.tenant_schema import TenantBusinessConversion

    factory, tenant_id, _ = team_db
    review.BusinessUpgradeReviewEntity.__table__.create(factory.kw["bind"])
    monkeypatch.setattr(review, "SessionLocal", factory)
    monkeypatch.setattr(review, "protect_cnpj", lambda _value: ("encrypted", "lookup", "**.***.***/****-81"))
    with factory.begin() as db:
        db.get(TenantEntity, tenant_id).kind = "personal"
    payload = TenantBusinessConversion(legal_name="Example company", cnpj="11.222.333/0001-81")
    subject = "member0@example.local"
    with pytest.raises(WorkflowError, match="Tenant access denied"):
        review.request_review(tenant_id, payload, "member1@example.local")
    requested = review.request_review(tenant_id, payload, subject)
    assert requested.status == "pending"
    assert review.request_review(tenant_id, payload, subject) == requested
    assert "encrypted" not in requested.model_dump()
    review.record_decision(requested.id, "approved", "operator")
    assert review.request_review(tenant_id, payload, subject).status == "approved"
    with factory() as db:
        assert db.get(TenantEntity, tenant_id).kind == "personal"
        assert db.get(review.BusinessUpgradeReviewEntity, requested.id).reviewed_by == "operator"


@pytest.mark.parametrize("branch", [False, True])
def test_approved_business_checkout_activates_separate_workspace_only_after_paid_invoice(team_db, monkeypatch, branch):
    from core_api.modules.billing import billing_service as billing
    from core_api.modules.billing.billing_service import BillingService
    from core_api.modules.billing.providers.fake_provider import FakeBillingProvider
    from core_api.modules.tenant import business_upgrade_review as review
    from core_api.infrastructure.settings import settings
    from core_api.modules.tenant.tenant_schema import TenantBusinessConversion

    factory, tenant_id, _ = team_db
    review.BusinessUpgradeReviewEntity.__table__.create(factory.kw["bind"])
    monkeypatch.setattr(review, "SessionLocal", factory)
    monkeypatch.setattr(billing, "SessionLocal", factory)
    monkeypatch.setattr(review, "protect_cnpj", lambda _value: ("encrypted", "lookup", "**.***.***/****-81"))
    monkeypatch.setattr(BillingService, "_price_for_currency", staticmethod(lambda *_args: "price_test"))
    monkeypatch.setattr(BillingService, "_record_payment", staticmethod(lambda *_args: None))
    monkeypatch.setattr(settings, "STRIPE_PRICE_TEAM_BRANCH_MONTHLY_BRL", "price_test_branch")
    with factory.begin() as db:
        source = db.get(TenantEntity, tenant_id)
        source.kind = "business" if branch else "personal"
        source.country_code = "BR"
        db.scalar(select(BillingAccountEntity)).current_product_code = "rubrica_base"

    subject = "member0@example.local"
    service = BillingService(FakeBillingProvider())
    payload = TenantBusinessConversion(legal_name="Separate company", cnpj="11.222.333/0001-81")
    if branch:
        with pytest.raises(WorkflowError, match="active Team subscription"):
            review.request_review(tenant_id, payload, subject, branch=True)
        with factory.begin() as db:
            db.scalar(select(BillingAccountEntity)).current_product_code = "rubrica_team"
    requested = review.request_review(
        tenant_id, payload, subject, branch=branch,
    )
    checkout_options = {"branch_review_id": requested.id} if branch else {}
    with pytest.raises(WorkflowError, match="approved before checkout"):
        service.create_checkout(tenant_id, subject, "rubrica_team", **checkout_options)
    review.record_decision(requested.id, "approved", "operator")
    service.create_checkout(tenant_id, subject, "rubrica_team", **checkout_options)
    service.create_checkout(tenant_id, subject, "rubrica_team", **checkout_options)

    with factory.begin() as db:
        destination_id = db.get(review.BusinessUpgradeReviewEntity, requested.id).business_tenant_id
        destination = db.get(TenantEntity, destination_id)
        account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == destination_id))
        BillingService._apply_event(db, "checkout.session.completed", {
            "id": "cs_test", "customer": account.provider_customer_id, "subscription": "sub_test",
            "metadata": {"product_code": "rubrica_team"},
        }, destination_id)
        assert destination.status == "pending_billing"
        assert destination.parent_workspace_id == (tenant_id if branch else None)

    assert [item.id for item in module.tenant_service.list_for(subject)] == [tenant_id]
    with factory.begin() as db:
        account = db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == destination_id))
        invoice = {"id": "in_test", "customer": account.provider_customer_id, "status": "paid"}
        BillingService._apply_event(db, "invoice.payment_succeeded", invoice, destination_id)
        assert db.get(TenantEntity, destination_id).status == "pending_billing"
        BillingService._apply_event(
            db, "invoice.payment_succeeded", invoice | {"billing_reason": "subscription_create"}, destination_id
        )

    if branch:
        assert review.list_branch_reviews(tenant_id, subject)[0].workspace_active
        assert module.tenant_service.team(destination_id, subject).member_limit == 10
        assert destination_id not in {item.id for item in module.tenant_service.list_for("member1@example.local")}
    workspaces = module.tenant_service.list_for(subject)
    assert {item.id for item in workspaces} == {tenant_id, destination_id}
    assert {item.id for item in workspaces if item.workspace_selectable} == {tenant_id, destination_id}
    with factory() as db:
        assert db.get(TenantEntity, tenant_id).kind == ("business" if branch else "personal")
        assert db.scalar(select(BillingAccountEntity).where(BillingAccountEntity.tenant_id == tenant_id)).current_product_code == ("rubrica_team" if branch else "rubrica_base")


def test_offboarding_revokes_seat_links_and_readmission_can_reset_history(team_db, monkeypatch):
    from core_api.modules.signature_request import database_workflow_service as workflow

    factory, tenant_id, ids = team_db
    tenant_service = module.tenant_service
    monkeypatch.setattr(workflow, "SessionLocal", factory)
    documents = DatabaseSignatureWorkflowService(None)
    admin = "member0@example.local"
    member = "member1@example.local"
    now = DateTimeService.utc_now()
    with factory.begin() as db:
        db.scalar(select(BillingAccountEntity)).current_period_ends_at = now + timedelta(days=1)
        document = DocumentEntity(
            tenant_id=tenant_id, organization_id="team-test", title="Old file",
            original_filename="test.pdf", content_type="application/pdf", storage_key="old",
            sha256="f" * 64, version=1, status="ready", created_by=member,
            created_at=now - timedelta(days=1),
        )
        db.add(document)
        db.flush()
        document_id = document.id
        request = SignatureRequestEntity(
            document_id=document.id, document_version=1, document_sha256="f" * 64,
            status="open", expires_at=now + timedelta(days=2), created_by=member,
        )
        db.add(request)
        db.flush()
        db.add(SignerEntity(
            signature_request_id=request.id, auth_user_id=member, name="Test member", email=member,
            signing_token_hash="s" * 64, token_expires_at=now + timedelta(days=2), status="pending",
        ))

    tenant_service.schedule_seat_roster(tenant_id, TenantSeatRosterUpdate(member_ids=ids), admin)
    tenant_service.update_member_access(tenant_id, ids[1], "offboard", admin)
    assert tenant_service.list_for(member) == []
    with pytest.raises(WorkflowError, match="Tenant access denied"):
        documents.get_document(str(document_id), member)
    with factory.begin() as db:
        roster = db.scalar(select(TenantSeatRosterEntity))
        assert str(ids[1]) not in roster.member_ids
        assert db.scalar(select(SignerEntity)).link_revoked_at is not None
        tenant_service.apply_due_seat_roster(db, tenant_id, through=roster.cycle_starts_at)
        assert db.get(TenantMemberEntity, ids[1]).status == "offboarded"

    tenant_service.update_member_access(tenant_id, ids[1], "restore", admin)
    assert documents.get_document(str(document_id), member).title == "Old file"
    tenant_service.update_member_access(tenant_id, ids[1], "offboard", admin)
    tenant_service.update_member_access(tenant_id, ids[1], "fresh", admin)
    assert documents.list_documents(member) == []
    assert documents.list_requests(member) == []
    assert documents.get_document(str(document_id), admin).title == "Old file"


def test_company_only_signing_scopes_immediate_policy_to_issuing_workspace(team_db):
    from types import SimpleNamespace

    factory, tenant_id, ids = team_db
    admin = "member0@example.local"
    member = "member1@example.local"
    with factory.begin() as db:
        doc = DocumentEntity(
            tenant_id=tenant_id, organization_id="team-test", title="Business PDF",
            original_filename="test.pdf", content_type="application/pdf", storage_key="company",
            sha256="f" * 64, version=1, status="ready", created_by=admin,
        )
        db.add(doc)
        db.flush()
        request = SimpleNamespace(document_id=doc.id)
    signer = SimpleNamespace(
        link_revoked_at=None, participant_role="external_signer", represented_tenant_id=None,
    )
    check = DatabaseSignatureWorkflowService._require_workspace_signing_permission
    with factory() as db:
        check(db, request, signer, member)
    module.tenant_service.update_document_scope(tenant_id, ids[1], None, admin, sign_company_only=True)
    with factory() as db:
        with pytest.raises(WorkflowError, match="can only sign as a representative"):
            check(db, request, signer, member)
        signer.participant_role = "company_representative"
        signer.represented_tenant_id = tenant_id
        check(db, request, signer, member)
        db.get(TenantEntity, tenant_id).kind = "personal"
        db.flush()
        signer.participant_role = "external_signer"
        signer.represented_tenant_id = None
        check(db, request, signer, member)


def test_workspace_admin_can_transfer_management_to_an_active_member(team_db):
    _, tenant_id, members = team_db
    owner = "member0@example.local"
    successor = "member1@example.local"
    service = module.tenant_service

    service.update_member_role(tenant_id, members[1], "admin", owner)
    assert service.team(tenant_id, successor).can_manage
    service.update_member_role(tenant_id, members[0], "member", successor)
    with pytest.raises(WorkflowError, match="Tenant access denied"):
        service.team(tenant_id, owner)


def test_workspace_admin_transfer_preserves_the_scheduled_successor(team_db):
    factory, tenant_id, members = team_db
    owner = "member0@example.local"
    successor = "member1@example.local"
    service = module.tenant_service
    with factory.begin() as db:
        db.scalar(select(BillingAccountEntity)).current_period_ends_at = (
            DateTimeService.utc_now() + timedelta(days=1)
        )

    service.update_member_role(tenant_id, members[1], "admin", owner)
    service.schedule_seat_roster(tenant_id, TenantSeatRosterUpdate(member_ids=[members[0]]), owner)
    with pytest.raises(WorkflowError, match="Schedule a successor"):
        service.update_member_role(tenant_id, members[0], "member", successor)


def test_organization_admin_branch_access_is_scoped_and_revocable(team_db, monkeypatch):
    from core_api.modules.signature_request import database_workflow_service as workflow

    factory, root_id, ids = team_db
    monkeypatch.setattr(workflow, "SessionLocal", factory)
    with factory.begin() as db:
        branch = TenantEntity(name="Branch", slug="branch", kind="business", parent_workspace_id=root_id)
        private = TenantEntity(name="Personal", slug="personal-scope", kind="personal")
        db.add_all([branch, private])
        db.flush()
        branch_id = branch.id
        db.add(BillingAccountEntity(tenant_id=branch_id, status="active", current_product_code="rubrica_team"))
        db.add(TenantMemberEntity(tenant_id=branch_id, auth_user_id="branch-manager@example.local", role="admin"))
        for tenant in [branch, private]:
            db.add(DocumentEntity(
                tenant_id=tenant.id, organization_id=tenant.slug, title=tenant.name,
                original_filename="test.pdf", content_type="application/pdf",
                storage_key=tenant.slug, sha256="f" * 64, version=1,
                status="ready", created_by="somebody@example.local",
            ))
        db.flush()
        doc = db.scalar(select(DocumentEntity).where(DocumentEntity.tenant_id == branch_id))
        document_id = doc.id
        request = SignatureRequestEntity(
            document_id=document_id, document_version=1, document_sha256="f" * 64,
            status="draft", expires_at=DateTimeService.utc_now() + timedelta(days=1),
            created_by="branch-manager@example.local",
        )
        db.add(request)
    service = module.tenant_service
    docs = DatabaseSignatureWorkflowService(None)
    owner = "member0@example.local"
    successor = "member1@example.local"
    manager = "branch-manager@example.local"

    assert {tenant.id for tenant in service.list_for(owner)} == {root_id, branch_id}
    assert {tenant.id for tenant in service.list_for(manager)} == {branch_id}
    assert [doc.title for doc in docs.list_documents(owner)] == ["Branch"]
    assert len(docs.list_requests(owner)) == 1
    assert docs.get_document(str(document_id), owner).title == "Branch"
    assert service.team(branch_id, owner).can_manage
    with pytest.raises(WorkflowError, match="Tenant access denied"):
        service.team(root_id, manager)

    service.update_member_role(root_id, ids[1], "admin", owner)
    service.update_member_role(root_id, ids[0], "member", successor)
    assert docs.list_documents(owner) == []
    assert docs.list_requests(owner) == []
    with pytest.raises(WorkflowError, match="Tenant access denied"):
        docs.get_document(str(document_id), owner)
    assert docs.get_document(str(document_id), successor).title == "Branch"


def test_closure_request_is_audited_reversible_and_leaves_workspace_active(team_db):
    factory, tenant_id, _ = team_db
    service = module.tenant_service
    admin = "member0@example.local"
    with pytest.raises(WorkflowError, match="Tenant access denied"):
        service.update_closure_request(tenant_id, "member1@example.local", requested=True)

    first = service.update_closure_request(tenant_id, admin, requested=True)
    assert first.closure_requested_at is not None
    assert service.update_closure_request(tenant_id, admin, requested=True).closure_requested_at == first.closure_requested_at
    assert service.update_closure_request(tenant_id, admin, requested=False).closure_requested_at is None
    with factory() as db:
        assert db.get(TenantEntity, tenant_id).status == "active"
        assert set(db.scalars(select(AuditEventEntity.action))) == {
            "tenant.closure_requested", "tenant.closure_withdrawn",
        }


def test_closed_workspace_revokes_links_and_allows_only_temporary_admin_export(team_db, monkeypatch):
    from core_api.modules.signature_request import database_workflow_service as workflow

    factory, tenant_id, _ = team_db
    monkeypatch.setattr(workflow, "SessionLocal", factory)
    with factory.begin() as db:
        doc = DocumentEntity(
            tenant_id=tenant_id, organization_id="team-test", title="Archive",
            original_filename="archive.pdf", content_type="application/pdf",
            storage_key="archive", sha256="a" * 64, version=1, status="ready",
            created_by="member1@example.local",
        )
        db.add(doc)
        db.flush()
        doc_id = doc.id
        request = SignatureRequestEntity(
            document_id=doc.id, document_version=1, document_sha256="a" * 64,
            status="open", expires_at=DateTimeService.utc_now() + timedelta(days=1),
            created_by="member1@example.local",
        )
        db.add(request)
        db.flush()
        req_id = request.id

    admin, member = "member0@example.local", "member1@example.local"
    service = module.tenant_service
    docs = DatabaseSignatureWorkflowService(None)
    service.update_closure_request(tenant_id, admin, requested=True)
    closure = service.close_workspace(tenant_id, admin)
    assert closure.export_until is not None
    assert service.close_workspace(tenant_id, admin).export_until == closure.export_until
    assert docs.get_document(str(doc_id), admin).title == "Archive"
    assert docs.list_documents(member) == []
    with pytest.raises(WorkflowError, match="Workspace is closed"):
        docs.get_document(str(doc_id), member)
    with pytest.raises(WorkflowError, match="Workspace is closed"):
        docs.delete_document(str(doc_id), admin)

    with factory.begin() as db:
        assert db.get(SignatureRequestEntity, req_id).status == "cancelled"
        db.get(TenantEntity, tenant_id).workspace_closed_at = DateTimeService.utc_now() - timedelta(days=31)
    with pytest.raises(WorkflowError, match="Workspace is closed"):
        docs.get_document(str(doc_id), admin)
    assert service.list_for(admin) == []
    with factory() as db:
        assert db.get(DocumentEntity, doc_id).deleted_at is None
