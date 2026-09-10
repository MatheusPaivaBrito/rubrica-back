import pytest
from types import SimpleNamespace
from uuid import uuid4

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


class BillingDatabaseStub:
    def __init__(self, account) -> None:
        self.account = account

    def scalar(self, _statement):
        return self.account


def test_completed_checkout_does_not_unlock_unlimited_signatures(monkeypatch) -> None:
    account = SimpleNamespace(
        status="not_configured",
        provider=None,
        provider_customer_id=None,
        provider_subscription_id=None,
        current_product_code=None,
        current_period_ends_at=None,
    )
    monkeypatch.setattr(BillingService, "_account_entity", lambda *_args: account)

    BillingService._apply_event(
        object(),
        "checkout.session.completed",
        {"subscription": "sub_test"},
        uuid4(),
    )

    assert account.status == "pending"
    assert account.provider_subscription_id == "sub_test"


def test_free_account_consumes_each_completed_signer_signature() -> None:
    account = SimpleNamespace(
        status="not_configured",
        signatures_used=4,
        free_signatures_limit=5,
        deleted_at=None,
    )

    BillingService().consume_signature(BillingDatabaseStub(account), uuid4())

    assert account.signatures_used == 5


def test_free_account_rejects_the_sixth_signer_signature() -> None:
    account = SimpleNamespace(
        status="cancelled",
        signatures_used=5,
        free_signatures_limit=5,
        deleted_at=None,
    )

    with pytest.raises(WorkflowError) as error:
        BillingService().consume_signature(BillingDatabaseStub(account), uuid4())

    assert error.value.status_code == 402
    assert account.signatures_used == 5


def test_active_subscription_is_unlimited_but_keeps_lifetime_usage() -> None:
    account = SimpleNamespace(
        status="active",
        signatures_used=31,
        free_signatures_limit=5,
        deleted_at=None,
    )

    BillingService().consume_signature(BillingDatabaseStub(account), uuid4())

    assert account.signatures_used == 32
