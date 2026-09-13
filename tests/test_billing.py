from datetime import UTC, datetime, timedelta

import pytest
from types import SimpleNamespace
from uuid import uuid4

from core_api.modules.billing.billing_service import BillingService
from core_api.infrastructure.settings import settings
from core_api.modules.signature_request.workflow_service import WorkflowError


@pytest.mark.parametrize(
    ("provider_status", "expected"),
    [
        ("trialing", "active"),
        ("active", "active"),
        ("past_due", "past_due"),
        ("unpaid", "unpaid"),
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


def test_older_subscription_event_is_ignored(monkeypatch) -> None:
    tenant_id = uuid4()
    current = datetime(2026, 9, 10, tzinfo=UTC)
    account = SimpleNamespace(status="active", provider=None, provider_customer_id=None, provider_subscription_id="sub_test", current_product_code="rubrica_mvp", current_period_ends_at=None, grace_period_ends_at=None, last_provider_event_created_at=current)
    monkeypatch.setattr(BillingService, "_account_entity", lambda *_args: account)
    applied = BillingService._apply_event(object(), "customer.subscription.updated", {"id": "sub_test", "status": "canceled", "metadata": {}}, tenant_id, current - timedelta(minutes=1))
    assert applied is False
    assert account.status == "active"


def test_past_due_account_keeps_access_during_grace_period() -> None:
    account = SimpleNamespace(status="past_due", signatures_used=5, free_signatures_limit=5, deleted_at=None, grace_period_ends_at=datetime.now(UTC) + timedelta(days=1))
    BillingService().consume_signature(BillingDatabaseStub(account), uuid4())
    assert account.signatures_used == 6


def test_default_payment_grace_period_is_ten_days() -> None:
    assert settings.BILLING_GRACE_PERIOD_DAYS == 10


def test_failed_invoice_starts_grace_period_and_records_payment(monkeypatch) -> None:
    account = SimpleNamespace(
        status="active",
        provider=None,
        provider_customer_id=None,
        grace_period_ends_at=None,
        current_period_ends_at=None,
    )
    recorded: dict[str, object] = {}
    monkeypatch.setattr(BillingService, "_account_entity", lambda *_args: account)
    monkeypatch.setattr(
        BillingService,
        "_record_payment",
        lambda _db, _tenant_id, event_type, resource, event_id: recorded.update(
            event_type=event_type,
            invoice_id=resource["id"],
            event_id=event_id,
        ),
    )

    BillingService._apply_event(
        object(),
        "invoice.payment_failed",
        {
            "id": "in_test",
            "lines": {
                "data": [
                    {"period": {"start": 1_790_000_000, "end": 1_800_000_000}}
                ]
            },
        },
        uuid4(),
        provider_event_id="evt_test",
    )

    assert account.status == "past_due"
    assert account.grace_period_ends_at is not None
    assert account.current_period_ends_at is None
    assert recorded == {
        "event_type": "invoice.payment_failed",
        "invoice_id": "in_test",
        "event_id": "evt_test",
    }


def test_successful_invoice_restores_active_access(monkeypatch) -> None:
    account = SimpleNamespace(
        status="past_due",
        provider=None,
        provider_customer_id=None,
        grace_period_ends_at=datetime.now(UTC) + timedelta(days=1),
        current_period_ends_at=None,
    )
    monkeypatch.setattr(BillingService, "_account_entity", lambda *_args: account)
    monkeypatch.setattr(BillingService, "_record_payment", lambda *_args: None)

    BillingService._apply_event(
        object(),
        "invoice.payment_succeeded",
        {"id": "in_test"},
        uuid4(),
    )

    assert account.status == "active"
    assert account.grace_period_ends_at is None


@pytest.mark.parametrize("locale", ["en", "pt-BR", "es", "ja-JP"])
def test_billing_messages_are_localized(locale: str) -> None:
    message = BillingService._billing_message(locale, "invoice.payment_failed")

    assert message is not None
    assert "{tenant}" in message[1]


def test_irrelevant_stripe_event_does_not_send_billing_email() -> None:
    assert BillingService._billing_message("en", "customer.updated") is None


def test_subscription_email_reflects_provider_status() -> None:
    message = BillingService._billing_message(
        "en",
        "customer.subscription.created",
        "incomplete",
    )

    assert message is not None
    assert message[0] == "Rubrica payment failed"


def test_unchanged_subscription_status_does_not_send_duplicate_status_email() -> None:
    assert (
        BillingService._billing_message(
            "en",
            "customer.subscription.updated",
            "active",
            "active",
        )
        is None
    )


def test_invoice_service_period_prefers_subscription_line_period() -> None:
    start, end = BillingService._invoice_service_period(
        {
            "period_start": 1,
            "period_end": 2,
            "lines": {"data": [{"period": {"start": 10, "end": 20}}]},
        }
    )

    assert start == datetime.fromtimestamp(10, tz=UTC)
    assert end == datetime.fromtimestamp(20, tz=UTC)
