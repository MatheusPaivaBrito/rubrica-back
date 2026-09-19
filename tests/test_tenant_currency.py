import pytest

from core_api.modules.tenant.tenant_service import billing_currency_for_country


@pytest.mark.parametrize(
    ("country_code", "currency"),
    [
        ("BR", "BRL"),
        ("JP", "JPY"),
        ("PT", "EUR"),
        ("ES", "EUR"),
        ("DE", "EUR"),
        ("US", "USD"),
        ("CA", "USD"),
        (None, "USD"),
    ],
)
def test_billing_currency_follows_explicit_country(
    country_code: str | None, currency: str
) -> None:
    assert billing_currency_for_country(country_code) == currency
