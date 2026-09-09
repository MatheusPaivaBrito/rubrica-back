import pytest

from core_api.modules.billing.billing_service import BillingService
from core_api.modules.signature_request.workflow_service import WorkflowError


@pytest.mark.parametrize(
    ("provider_status", "expected"),
    [
        ("trialing", "active"),
        ("active", "active"),
        ("past_due", "past_due"),
        ("unpaid", "past_due"),
        ("canceled", "cancelled"),
        ("paused", "paused"),
        ("unknown", "not_configured"),
    ],
)
def test_stripe_subscription_status_is_mapped(
    provider_status: str,
    expected: str,
) -> None:
    assert BillingService._subscription_status(provider_status) == expected


def test_checkout_requires_a_configured_currency_price(monkeypatch) -> None:
    monkeypatch.setattr("core_api.modules.billing.billing_service.settings.STRIPE_PRICE_JPY", None)

    with pytest.raises(WorkflowError, match="JPY"):
        BillingService._price_for_currency("JPY")
