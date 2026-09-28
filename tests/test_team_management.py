from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core_api.infrastructure.auth_context import AuthContext, _active_auth_context
from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.signature_request.signature_request_entity import AuditEventEntity
from core_api.modules.signature_request.workflow_service import WorkflowError
from core_api.modules.tenant import tenant_service as module
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from core_api.modules.tenant.tenant_schema import TenantMemberInvitation, TenantTeamUpdate


@pytest.fixture
def team_db(monkeypatch):
    token = _active_auth_context.set(None)
    engine = create_engine('sqlite://')
    for entity in (TenantEntity, TenantMemberEntity, BillingAccountEntity, AuditEventEntity):
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
