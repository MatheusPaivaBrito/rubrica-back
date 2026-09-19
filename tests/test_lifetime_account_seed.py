import pytest
from uuid import uuid4

from toolbox.seeds.lifetime_account import _bounded, tenant_id_for_owner


def test_staff_audit_values_are_normalized() -> None:
    assert _bounded("  staff@example.com  ", "actor", 255) == "staff@example.com"


@pytest.mark.parametrize("value", ["", "   "])
def test_staff_audit_values_are_required(value: str) -> None:
    with pytest.raises(ValueError, match="is required"):
        _bounded(value, "reason", 500)


def test_staff_audit_values_have_a_safe_database_limit() -> None:
    with pytest.raises(ValueError, match="at most 500"):
        _bounded("x" * 501, "reason", 500)


class TenantDatabaseStub:
    def __init__(self, tenant_ids) -> None:
        self.tenant_ids = tenant_ids

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def scalars(self, _statement):
        return self

    def all(self):
        return self.tenant_ids


def test_owner_email_resolves_exactly_one_tenant(monkeypatch) -> None:
    tenant_id = uuid4()
    monkeypatch.setattr(
        "toolbox.seeds.lifetime_account.SessionLocal",
        lambda: TenantDatabaseStub([tenant_id]),
    )

    assert tenant_id_for_owner(" OWNER@Example.com ") == tenant_id


def test_owner_email_rejects_ambiguous_tenants(monkeypatch) -> None:
    monkeypatch.setattr(
        "toolbox.seeds.lifetime_account.SessionLocal",
        lambda: TenantDatabaseStub([uuid4(), uuid4()]),
    )

    with pytest.raises(ValueError, match="multiple tenants"):
        tenant_id_for_owner("owner@example.com")
