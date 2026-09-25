from datetime import UTC, datetime, timedelta

import pytest
from types import SimpleNamespace
from uuid import uuid4

from core_api.modules.billing.billing_service import BillingService
from core_api.modules.billing.providers.stripe_provider import StripeBillingProvider
from core_api.modules.billing.providers.protocol import ProviderBusinessIdentity, ProviderTaxId
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


@pytest.mark.parametrize(
    ("product_code", "currency", "setting_name"),
    [
        ("rubrica_base", "BRL", "STRIPE_PRICE_BRL"),
        ("rubrica_base", "USD", "STRIPE_PRICE_USD"),
        ("rubrica_base", "EUR", "STRIPE_PRICE_EUR"),
        ("rubrica_base", "JPY", "STRIPE_PRICE_JPY"),
        ("rubrica_intermediate", "BRL", "STRIPE_PRICE_INTERMEDIATE_BRL"),
        ("rubrica_intermediate", "USD", "STRIPE_PRICE_INTERMEDIATE_USD"),
        ("rubrica_intermediate", "EUR", "STRIPE_PRICE_INTERMEDIATE_EUR"),
        ("rubrica_intermediate", "JPY", "STRIPE_PRICE_INTERMEDIATE_JPY"),
        ("rubrica_team", "BRL", "STRIPE_PRICE_TEAM_BRL"),
        ("rubrica_team", "USD", "STRIPE_PRICE_TEAM_USD"),
        ("rubrica_team", "EUR", "STRIPE_PRICE_TEAM_EUR"),
        ("rubrica_team", "JPY", "STRIPE_PRICE_TEAM_JPY"),
    ],
)
def test_checkout_selects_price_for_every_plan_and_currency(
    monkeypatch, product_code: str, currency: str, setting_name: str
) -> None:
    expected = f"price_{product_code}_{currency.lower()}"
    monkeypatch.setattr(
        f"core_api.modules.billing.billing_service.settings.{setting_name}", expected
    )

    assert BillingService._price_for_currency(currency, product_code) == expected


@pytest.mark.parametrize(
    ("product_code", "setting_name"),
    [
        ("rubrica_base", "STRIPE_PRICE_ANNUAL_BRL"),
        ("rubrica_intermediate", "STRIPE_PRICE_INTERMEDIATE_ANNUAL_BRL"),
        ("rubrica_team", "STRIPE_PRICE_TEAM_ANNUAL_BRL"),
    ],
)
def test_checkout_selects_annual_price(monkeypatch, product_code: str, setting_name: str) -> None:
    expected = f"price_{product_code}_annual_brl"
    monkeypatch.setattr(f"core_api.modules.billing.billing_service.settings.{setting_name}", expected)
    assert BillingService._price_for_currency("BRL", product_code, "year") == expected


def test_team_plan_limits() -> None:
    assert BillingService.PLAN_MEMBER_LIMITS["rubrica_intermediate"] == 3
    assert BillingService.PLAN_MEMBER_LIMITS["rubrica_team"] == 10
    assert BillingService.PLAN_FILE_LIMITS["rubrica_team"] == 200


@pytest.mark.parametrize(
    "status",
    ["active", "pending", "past_due", "unpaid", "paused"],
)
def test_existing_subscription_must_be_changed_through_portal(status: str) -> None:
    account = SimpleNamespace(
        status=status,
        provider_subscription_id="sub_existing",
    )

    assert BillingService._subscription_requires_portal(account)


def test_cancelled_subscription_can_start_a_new_checkout() -> None:
    account = SimpleNamespace(
        status="cancelled",
        provider_subscription_id="sub_cancelled",
    )

    assert not BillingService._subscription_requires_portal(account)


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
    monkeypatch.setattr(
        BillingService, "_account_entity", lambda *_args, **_kwargs: account
    )

    BillingService._apply_event(
        object(),
        "checkout.session.completed",
        {"subscription": "sub_test"},
        uuid4(),
    )

    assert account.status == "pending"
    assert account.provider_subscription_id == "sub_test"


def test_professional_event_applies_stripe_cnpj_to_tenant(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "core_api.modules.billing.billing_service.tenant_service.apply_billing_business_identity",
        lambda _database, tenant_id, **values: captured.update(
            {"tenant_id": tenant_id, **values}
        ),
    )
    tenant_id = uuid4()
    identity = ProviderBusinessIdentity(
        name="Empresa Teste Ltda.",
        tax_ids=(
            ProviderTaxId(
                id="txi_cnpj",
                type="br_cnpj",
                value="11222333000181",
            ),
        ),
    )

    BillingService._apply_business_identity(
        object(), tenant_id, "rubrica_intermediate", identity
    )

    assert captured == {
        "tenant_id": tenant_id,
        "legal_name": "Empresa Teste Ltda.",
        "cnpj": "11222333000181",
        "provider_reference": "txi_cnpj",
    }


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


def test_active_subscription_does_not_consume_free_signature_allowance() -> None:
    account = SimpleNamespace(
        status="active",
        signatures_used=31,
        free_signatures_limit=5,
        deleted_at=None,
        grace_period_ends_at=None,
    )

    BillingService().consume_signature(BillingDatabaseStub(account), uuid4())
    assert account.signatures_used == 31
    assert not BillingService._has_unlimited_signatures(account)


def test_complimentary_lifetime_account_is_unlimited_without_stripe() -> None:
    account = SimpleNamespace(
        status="not_configured",
        complimentary_lifetime=True,
        signatures_used=50,
        free_signatures_limit=5,
        deleted_at=None,
    )

    BillingService().consume_signature(BillingDatabaseStub(account), uuid4())

    assert account.signatures_used == 50
    assert BillingService._has_unlimited_signatures(account)


def test_scheduled_cancellation_keeps_access_until_period_end(monkeypatch) -> None:
    account = SimpleNamespace(
        status="active",
        provider=None,
        provider_customer_id=None,
        provider_subscription_id="sub_test",
        current_product_code="rubrica_base",
        current_period_ends_at=None,
        grace_period_ends_at=None,
        last_provider_event_created_at=None,
        usage_period_starts_at=None,
        files_uploaded_in_period=7,
    )
    monkeypatch.setattr(
        BillingService, "_account_entity", lambda *_args, **_kwargs: account
    )

    period_end = 1_800_000_000
    BillingService._apply_event(
        object(),
        "customer.subscription.updated",
        {
            "id": "sub_test",
            "status": "active",
            "cancel_at_period_end": True,
            "items": {
                "data": [
                    {
                        "current_period_start": 1_799_000_000,
                        "current_period_end": period_end,
                    }
                ]
            },
        },
        uuid4(),
    )

    assert account.status == "active"
    assert account.cancel_at_period_end is True
    assert account.cancels_at == datetime.fromtimestamp(period_end, tz=UTC)
    assert account.files_uploaded_in_period == 7


def test_subscription_deleted_ends_paid_access(monkeypatch) -> None:
    account = SimpleNamespace(
        status="active",
        provider=None,
        provider_customer_id=None,
        provider_subscription_id="sub_test",
        current_product_code="rubrica_base",
        current_period_ends_at=None,
        grace_period_ends_at=None,
        last_provider_event_created_at=None,
        usage_period_starts_at=None,
        files_uploaded_in_period=7,
    )
    monkeypatch.setattr(
        BillingService, "_account_entity", lambda *_args, **_kwargs: account
    )

    BillingService._apply_event(
        object(),
        "customer.subscription.deleted",
        {
            "id": "sub_test",
            "status": "canceled",
            "cancel_at_period_end": True,
            "items": {
                "data": [
                    {
                        "current_period_start": 1_799_000_000,
                        "current_period_end": 1_800_000_000,
                    }
                ]
            },
        },
        uuid4(),
    )

    assert account.status == "cancelled"
    assert not BillingService._paid_access_enabled(account)


def test_essential_plan_limits_new_files_to_20_per_period() -> None:
    account = SimpleNamespace(
        status="active",
        current_product_code="rubrica_base",
        files_uploaded_in_period=19,
        complimentary_lifetime=False,
        deleted_at=None,
        grace_period_ends_at=None,
    )

    service = BillingService()
    service.consume_document(BillingDatabaseStub(account), uuid4())
    assert account.files_uploaded_in_period == 20

    with pytest.raises(WorkflowError) as error:
        service.consume_document(BillingDatabaseStub(account), uuid4())

    assert error.value.status_code == 402
    assert account.files_uploaded_in_period == 20


def test_professional_plan_limits_new_files_to_80_per_period() -> None:
    account = SimpleNamespace(
        status="active",
        current_product_code="rubrica_intermediate",
        files_uploaded_in_period=79,
        complimentary_lifetime=False,
        deleted_at=None,
        grace_period_ends_at=None,
    )

    BillingService().consume_document(BillingDatabaseStub(account), uuid4())

    assert account.files_uploaded_in_period == 80


def test_switching_plan_does_not_reset_usage_in_the_same_period() -> None:
    period_start = datetime(2026, 9, 1, tzinfo=UTC)
    account = SimpleNamespace(
        usage_period_starts_at=period_start,
        files_uploaded_in_period=10,
        current_period_ends_at=None,
    )

    BillingService._sync_usage_period(
        account,
        period_start,
        datetime(2026, 10, 1, tzinfo=UTC),
        reset_usage=False,
    )

    assert account.files_uploaded_in_period == 10


def test_upgrade_only_expands_the_same_period_allowance() -> None:
    account = SimpleNamespace(
        status="active",
        current_product_code="rubrica_intermediate",
        files_uploaded_in_period=25,
        complimentary_lifetime=False,
        deleted_at=None,
        grace_period_ends_at=None,
    )

    BillingService().consume_document(BillingDatabaseStub(account), uuid4())

    assert account.files_uploaded_in_period == 26


def test_downgrade_does_not_erase_usage_or_documents() -> None:
    account = SimpleNamespace(
        status="active",
        current_product_code="rubrica_base",
        files_uploaded_in_period=27,
        complimentary_lifetime=False,
        deleted_at=None,
        grace_period_ends_at=None,
    )

    with pytest.raises(WorkflowError) as error:
        BillingService().consume_document(BillingDatabaseStub(account), uuid4())

    assert error.value.status_code == 402
    assert account.files_uploaded_in_period == 27


def test_new_billing_period_resets_file_usage_once() -> None:
    account = SimpleNamespace(
        usage_period_starts_at=datetime(2026, 9, 1, tzinfo=UTC),
        files_uploaded_in_period=25,
        current_period_ends_at=None,
    )

    BillingService._sync_usage_period(
        account,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 11, 1, tzinfo=UTC),
        reset_usage=True,
    )

    assert account.files_uploaded_in_period == 0
    assert account.usage_period_starts_at == datetime(2026, 10, 1, tzinfo=UTC)


def test_plan_change_with_new_stripe_anchor_does_not_reset_usage() -> None:
    original_start = datetime(2026, 9, 1, tzinfo=UTC)
    account = SimpleNamespace(
        usage_period_starts_at=original_start,
        files_uploaded_in_period=18,
        current_period_ends_at=None,
    )

    BillingService._sync_usage_period(
        account,
        datetime(2026, 9, 15, tzinfo=UTC),
        datetime(2026, 10, 15, tzinfo=UTC),
        reset_usage=False,
    )

    assert account.files_uploaded_in_period == 18
    assert account.usage_period_starts_at == original_start


def test_subscription_price_takes_precedence_over_old_plan_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.billing_service.settings.STRIPE_PRICE_INTERMEDIATE_BRL",
        "price_intermediate",
    )

    product_code = BillingService._product_code(
        {
            "metadata": {"product_code": "rubrica_base"},
            "items": {"data": [{"price": {"id": "price_intermediate"}}]},
        }
    )

    assert product_code == "rubrica_intermediate"


def test_subscription_period_supports_stripe_item_level_periods() -> None:
    start, end = BillingService._subscription_period(
        {
            "items": {
                "data": [
                    {
                        "current_period_start": 1_799_000_000,
                        "current_period_end": 1_801_000_000,
                    }
                ]
            }
        }
    )

    assert start == datetime.fromtimestamp(1_799_000_000, tz=UTC)
    assert end == datetime.fromtimestamp(1_801_000_000, tz=UTC)


def test_only_active_intermediate_plan_enables_signature_invitation_email() -> None:
    intermediate = SimpleNamespace(
        status="active",
        current_product_code="rubrica_intermediate",
        deleted_at=None,
        grace_period_ends_at=None,
    )
    base = SimpleNamespace(
        status="active",
        current_product_code="rubrica_base",
        deleted_at=None,
        grace_period_ends_at=None,
    )

    assert BillingService.email_invitations_enabled(
        BillingDatabaseStub(intermediate), uuid4()
    )
    assert not BillingService.email_invitations_enabled(
        BillingDatabaseStub(base), uuid4()
    )


def test_complimentary_lifetime_account_enables_signature_invitation_email() -> None:
    account = SimpleNamespace(
        status="not_configured",
        current_product_code=None,
        complimentary_lifetime=True,
        deleted_at=None,
        grace_period_ends_at=None,
    )

    assert BillingService.email_invitations_enabled(
        BillingDatabaseStub(account), uuid4()
    )

def test_older_subscription_event_is_ignored(monkeypatch) -> None:
    tenant_id = uuid4()
    current = datetime(2026, 9, 10, tzinfo=UTC)
    account = SimpleNamespace(status="active", provider=None, provider_customer_id=None, provider_subscription_id="sub_test", current_product_code="rubrica_mvp", current_period_ends_at=None, grace_period_ends_at=None, last_provider_event_created_at=current)
    monkeypatch.setattr(
        BillingService, "_account_entity", lambda *_args, **_kwargs: account
    )
    applied = BillingService._apply_event(object(), "customer.subscription.updated", {"id": "sub_test", "status": "canceled", "metadata": {}}, tenant_id, current - timedelta(minutes=1))
    assert applied is False
    assert account.status == "active"


def test_past_due_account_keeps_access_during_grace_period() -> None:
    account = SimpleNamespace(status="past_due", signatures_used=5, free_signatures_limit=5, deleted_at=None, grace_period_ends_at=datetime.now(UTC) + timedelta(days=1))
    BillingService().consume_signature(BillingDatabaseStub(account), uuid4())
    assert account.signatures_used == 5


def test_default_payment_grace_period_is_ten_days() -> None:
    assert settings.BILLING_GRACE_PERIOD_DAYS == 10


def test_runtime_stripe_webhook_secret_overrides_static_secret(
    monkeypatch, tmp_path
) -> None:
    runtime_secret = tmp_path / "stripe_webhook_secret"
    runtime_secret.write_text("whsec_runtime\n", encoding="utf-8")
    monkeypatch.setattr(settings, "STRIPE_RUNTIME_WEBHOOK_SECRET_FILE", str(runtime_secret))
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_static")

    assert StripeBillingProvider._webhook_secret() == "whsec_runtime"


def test_missing_runtime_stripe_webhook_secret_uses_static_secret(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        settings,
        "STRIPE_RUNTIME_WEBHOOK_SECRET_FILE",
        str(tmp_path / "missing"),
    )
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_static")

    assert StripeBillingProvider._webhook_secret() == "whsec_static"


def test_failed_invoice_starts_grace_period_and_records_payment(monkeypatch) -> None:
    account = SimpleNamespace(
        status="active",
        provider=None,
        provider_customer_id=None,
        grace_period_ends_at=None,
        current_period_ends_at=None,
    )
    recorded: dict[str, object] = {}
    monkeypatch.setattr(
        BillingService, "_account_entity", lambda *_args, **_kwargs: account
    )
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
    monkeypatch.setattr(
        BillingService, "_account_entity", lambda *_args, **_kwargs: account
    )
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


def test_plan_change_has_dedicated_localized_email() -> None:
    message = BillingService._billing_message(
        "pt-BR",
        "customer.subscription.updated",
        "active",
        "active",
        "rubrica_base",
        "rubrica_intermediate",
    )

    assert message is not None
    assert message[0] == "Plano Rubrica atualizado"
    assert "Essencial para Profissional" in message[1]
    assert "80 PDFs" in message[1]
    assert message[2] == "ATUALIZAÇÃO DE PLANO"


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


def test_only_professional_or_complimentary_accounts_enable_business_features() -> None:
    tenant_id = uuid4()
    professional = SimpleNamespace(
        deleted_at=None,
        complimentary_lifetime=False,
        current_product_code="rubrica_intermediate",
        status="active",
        grace_period_ends_at=None,
    )
    essential = SimpleNamespace(
        deleted_at=None,
        complimentary_lifetime=False,
        current_product_code="rubrica_base",
        status="active",
        grace_period_ends_at=None,
    )
    complimentary = SimpleNamespace(
        deleted_at=None,
        complimentary_lifetime=True,
        current_product_code=None,
        status="not_configured",
        grace_period_ends_at=None,
    )

    assert BillingService.business_features_enabled(BillingDatabaseStub(professional), tenant_id)
    assert not BillingService.business_features_enabled(BillingDatabaseStub(essential), tenant_id)
    assert BillingService.business_features_enabled(BillingDatabaseStub(complimentary), tenant_id)
