from uuid import uuid4

import pytest

from toolbox.seeds.business_tenant import BusinessTenantMigrationResult, _email, _legal_name


def test_business_migration_result_never_contains_full_cnpj() -> None:
    result = BusinessTenantMigrationResult(
        tenant_id=uuid4(),
        registration_masked="••.•••.•••/••••-81",
        tenant_changed=True,
        member_changed=True,
    )
    assert "11222333000181" not in repr(result)


def test_business_migration_normalizes_emails() -> None:
    assert _email("  OWNER@Example.com ", "owner") == "owner@example.com"


@pytest.mark.parametrize("value", ["", "invalid", "a" * 256 + "@example.com"])
def test_business_migration_rejects_invalid_emails(value: str) -> None:
    with pytest.raises(ValueError, match="valid email"):
        _email(value, "owner")


def test_business_migration_normalizes_legal_name() -> None:
    assert _legal_name("  Instituto Exemplo Ltda.  ") == "Instituto Exemplo Ltda."
