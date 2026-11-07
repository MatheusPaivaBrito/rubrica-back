from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from core_api.modules.billing.billing_entity import BillingAccountEntity
from core_api.modules.tenant.tenant_entity import TenantEntity, TenantMemberEntity
from toolbox.seeds import local_test_accounts as seed
from toolbox.seeds.local_accounts_catalog import ACCOUNTS, ENTERPRISE, LIFETIME


def test_enterprise_catalog_appends_unique_accounts_preserving_existing_cpf_positions():
    assert len(ENTERPRISE) == 3
    assert ACCOUNTS[-3:] == ENTERPRISE
    assert ACCOUNTS[11:14] == LIFETIME
    assert len({email for email, _ in ACCOUNTS}) == len(ACCOUNTS)


def test_enterprise_business_fixture_is_idempotent_and_preserves_scenarios(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (TenantEntity, TenantMemberEntity, BillingAccountEntity):
        model.__table__.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(seed, "CoreSessionLocal", sessions)
    users = {email: uuid4() for email, _ in ENTERPRISE}
    args = (users, ENTERPRISE, "90000000000184", "Empresarial API Local de Testes Ltda.", "rubrica_enterprise")
    try:
        seed._business_tenant(*args)
        with sessions() as db:
            account = db.scalar(select(BillingAccountEntity))
            assert account.current_product_code == "rubrica_enterprise"
            assert account.provider == "fake" and account.status == "active"
            assert not account.complimentary_lifetime
            members = db.scalars(select(TenantMemberEntity)).all()
            assert len(members) == 3 and sum(member.role == "admin" for member in members) == 1
        with sessions.begin() as db:
            account = db.scalar(select(BillingAccountEntity))
            account.current_product_code, account.status = "rubrica_team", "cancelled"
        seed._business_tenant(*args)
        with sessions() as db:
            assert db.scalar(select(func.count()).select_from(TenantEntity)) == 1
            assert db.scalar(select(func.count()).select_from(TenantMemberEntity)) == 3
            account = db.scalar(select(BillingAccountEntity))
            assert account.current_product_code == "rubrica_team" and account.status == "cancelled"
    finally:
        engine.dispose()


def test_main_adds_enterprise_without_resetting_other_fixtures(monkeypatch, capsys):
    users = {email: uuid4() for email, _ in ACCOUNTS}
    monkeypatch.setattr(seed, "require_test_environment", lambda: "staging")
    monkeypatch.setenv("LOCAL_TEST_ACCOUNT_PASSWORD", "fictional-seed-password")
    monkeypatch.setattr(seed, "_auth_users", lambda _: users)
    for name in ("_personal_tenants", "_essential_plan", "_lifetime_tenant", "_archive_empty_legacy_personal_tenants"):
        monkeypatch.setattr(seed, name, lambda _: None)
    monkeypatch.setattr(seed, "_expired_signature_request_fixture", lambda: None)
    calls = []
    monkeypatch.setattr(seed, "_business_tenant", lambda *args: calls.append(args))
    seed.main()
    enterprise = [args for args in calls if args[-1] == "rubrica_enterprise"]
    assert len(enterprise) == 1 and enterprise[0][1] == ENTERPRISE
    assert "17 staging test accounts" in capsys.readouterr().out


def test_enterprise_seed_stays_forbidden_in_production(monkeypatch):
    import pytest
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOW_STAGING_TEST_SEED", "1")
    with pytest.raises(RuntimeError, match="explicit local/development/staging"):
        seed.require_test_environment()


def test_staging_seed_requires_explicit_opt_in(monkeypatch):
    import pytest
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("ALLOW_STAGING_TEST_SEED", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_STAGING_TEST_SEED=1"):
        seed.require_test_environment()
