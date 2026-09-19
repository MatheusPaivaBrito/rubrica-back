import pytest

from toolbox.seeds.lifetime_account import _bounded


def test_staff_audit_values_are_normalized() -> None:
    assert _bounded("  staff@example.com  ", "actor", 255) == "staff@example.com"


@pytest.mark.parametrize("value", ["", "   "])
def test_staff_audit_values_are_required(value: str) -> None:
    with pytest.raises(ValueError, match="is required"):
        _bounded(value, "reason", 500)


def test_staff_audit_values_have_a_safe_database_limit() -> None:
    with pytest.raises(ValueError, match="at most 500"):
        _bounded("x" * 501, "reason", 500)
