"""Local fixtures must be isolated and safe to rerun during billing tests."""
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from toolbox.seeds import local_test_accounts as seed
from toolbox.seeds import lifetime_account as lifetime_module
from core_api.modules.tenant import tenant_service as tenant_module


@pytest.mark.parametrize("environment", [None, "production", "prod", "staging", "test"])
def test_seed_rejects_nonlocal_environment(monkeypatch, environment):
    monkeypatch.setenv("ALLOW_LOCAL_TEST_SEED", "1")
    if environment is None:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("ENVIRONMENT", environment)
    with pytest.raises(RuntimeError, match="ENVIRONMENT"):
        seed.main()


def test_seed_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("ALLOW_LOCAL_TEST_SEED", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_LOCAL_TEST_SEED"):
        seed.main()


def test_seed_preserves_downgrade_and_membership_state(monkeypatch):
    auth_engine = create_engine("sqlite://")
    core_engine = create_engine("sqlite://")
    for entity in (seed.UserEntity, seed.UserRoleEntity):
        entity.__table__.create(auth_engine)
    for entity in (seed.TenantEntity, seed.TenantMemberEntity, seed.BillingAccountEntity, lifetime_module.BillingEventEntity):
        entity.__table__.create(core_engine)
    auth = sessionmaker(auth_engine, expire_on_commit=False)
    core = sessionmaker(core_engine, expire_on_commit=False)
    monkeypatch.setattr(seed, "AuthSessionLocal", auth)
    monkeypatch.setattr(seed, "CoreSessionLocal", core)
    monkeypatch.setattr(lifetime_module, "SessionLocal", core)
    monkeypatch.setattr(tenant_module, "SessionLocal", core)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOW_LOCAL_TEST_SEED", "1")
    seed.main()
    with auth() as db:
        users = db.scalars(select(seed.UserEntity)).all()
        assert len(users) == 14
        assert all(u.email_verified and u.mfa_exempt and not u.mfa_enabled and u.is_active for u in users)
        ids = {u.id for u in users}
    with core.begin() as db:
        accounts = db.scalars(select(seed.BillingAccountEntity)).all()
        assert sum(a.current_product_code == "rubrica_base" for a in accounts) == 1
        for product, count in (("rubrica_intermediate", 3), ("rubrica_team", 6)):
            account = next(a for a in accounts if a.current_product_code == product)
            assert not account.complimentary_lifetime
            assert db.scalar(select(func.count()).select_from(seed.TenantMemberEntity).where(
                seed.TenantMemberEntity.tenant_id == account.tenant_id)) == count
        lifetime = next(a for a in accounts if a.complimentary_lifetime)
        assert lifetime.provider is None
        assert db.scalar(select(func.count()).select_from(seed.TenantMemberEntity).where(
            seed.TenantMemberEntity.tenant_id == lifetime.tenant_id)) == 3
        team_id = account.tenant_id
        account.current_product_code = "rubrica_intermediate"
        account.files_uploaded_in_period = 17
        member = db.scalar(select(seed.TenantMemberEntity).where(
            seed.TenantMemberEntity.tenant_id == team_id,
            seed.TenantMemberEntity.role == "member"))
        member.status = "suspended"
        member_id = member.id
    # Simulate an unused personal tenant left by the previous seed.
    with core.begin() as db:
        email, name = seed.TEAM[1]
        with auth() as auth_db:
            user_id = auth_db.scalar(select(seed.UserEntity.id).where(seed.UserEntity.email == email))
        legacy = seed.TenantEntity(name=name, slug="legacy-local-personal", kind="personal")
        db.add(legacy)
        db.flush()
        legacy_id = legacy.id
        db.add(seed.TenantMemberEntity(tenant_id=legacy_id, auth_user_id=email, auth_user_uuid=user_id, role="admin"))
        db.add(seed.BillingAccountEntity(tenant_id=legacy_id, status="not_configured"))
    seed.main()
    with auth() as db:
        assert set(db.scalars(select(seed.UserEntity.id))) == ids
    with core() as db:
        account = db.scalar(select(seed.BillingAccountEntity).where(seed.BillingAccountEntity.tenant_id == team_id))
        assert account.current_product_code == "rubrica_intermediate"
        assert account.files_uploaded_in_period == 17
        assert db.get(seed.TenantMemberEntity, member_id).status == "suspended"
        assert db.get(seed.TenantEntity, legacy_id).deleted_at is not None
        assert db.scalar(select(func.count()).select_from(seed.TenantEntity).where(seed.TenantEntity.deleted_at.is_(None))) == 5
