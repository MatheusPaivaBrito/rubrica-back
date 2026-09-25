from types import SimpleNamespace

import pytest

from core_api.modules.billing.providers.protocol import (
    BillingProviderError,
    InvalidWebhookSignatureError,
)
from core_api.modules.billing.providers.stripe_provider import StripeBillingProvider


def test_stripe_provider_requires_secret_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        None,
    )

    with pytest.raises(BillingProviderError, match="not configured"):
        StripeBillingProvider()


@pytest.mark.parametrize("product_code", ["rubrica_intermediate", "rubrica_team"])
def test_stripe_provider_builds_checkout_with_tenant_metadata(monkeypatch, product_code: str) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    captured: dict[str, object] = {}

    def create_checkout(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(url="https://checkout.stripe.test/session")

    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.checkout.Session.create",
        create_checkout,
    )

    session = StripeBillingProvider().create_checkout_session(
        customer_id="cus_test",
        price_id="price_jpy",
        product_code=product_code,
        tenant_id="019c-tenant",
        success_url="https://rubrica.test/plan?checkout=success",
        cancel_url="https://rubrica.test/plan?checkout=cancelled",
    )

    assert session.url == "https://checkout.stripe.test/session"
    assert captured["client_reference_id"] == "019c-tenant"
    assert captured["metadata"] == {
        "tenant_id": "019c-tenant",
        "product_code": product_code,
    }
    assert captured["subscription_data"] == {
        "metadata": {
            "tenant_id": "019c-tenant",
            "product_code": product_code,
        }
    }
    assert captured["line_items"] == [{"price": "price_jpy", "quantity": 1}]
    assert captured["tax_id_collection"] == {"enabled": True}
    assert captured["customer_update"] == {"name": "auto"}


def test_stripe_provider_does_not_collect_cnpj_for_essential_checkout(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    captured: dict[str, object] = {}

    def create_checkout(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(url="https://checkout.stripe.test/session")

    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.checkout.Session.create",
        create_checkout,
    )

    StripeBillingProvider().create_checkout_session(
        customer_id="cus_test",
        price_id="price_base",
        product_code="rubrica_base",
        tenant_id="019c-tenant",
        success_url="https://rubrica.test/plan?checkout=success",
        cancel_url="https://rubrica.test/plan?checkout=cancelled",
    )

    assert "tax_id_collection" not in captured
    assert "customer_update" not in captured


def test_stripe_provider_reads_customer_cnpj(monkeypatch) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Customer.retrieve",
        lambda _customer_id: {"name": "Empresa Teste Ltda."},
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Customer.list_tax_ids",
        lambda _customer_id, **_kwargs: {
            "data": [
                {
                    "id": "txi_cnpj",
                    "type": "br_cnpj",
                    "value": "11222333000181",
                }
            ]
        },
    )

    identity = StripeBillingProvider().retrieve_customer_business_identity("cus_test")

    assert identity.name == "Empresa Teste Ltda."
    assert identity.tax_ids[0].id == "txi_cnpj"
    assert identity.tax_ids[0].type == "br_cnpj"
    assert identity.tax_ids[0].value == "11222333000181"


def test_stripe_provider_translates_invalid_webhook_signature(monkeypatch) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_WEBHOOK_SECRET",
        "whsec_example",
    )

    def reject_webhook(*_args):
        raise ValueError("invalid payload")

    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Webhook.construct_event",
        reject_webhook,
    )

    with pytest.raises(InvalidWebhookSignatureError):
        StripeBillingProvider().construct_webhook_event(
            payload=b"{}",
            signature="invalid",
        )


def test_stripe_portal_opens_subscription_update_flow(monkeypatch) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    captured: dict[str, object] = {}

    def create_portal(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(url="https://billing.stripe.test/session")

    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.billing_portal.Session.create",
        create_portal,
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Subscription.retrieve",
        lambda _subscription_id: {"cancel_at_period_end": False},
    )

    session = StripeBillingProvider().create_portal_session(
        customer_id="cus_test",
        return_url="https://rubrica.test/plan",
        subscription_id="sub_test",
        completion_url="https://rubrica.test/plan?billing=updated",
    )

    assert session.url == "https://billing.stripe.test/session"
    assert captured["flow_data"] == {
        "type": "subscription_update",
        "subscription_update": {"subscription": "sub_test"},
        "after_completion": {
            "type": "redirect",
            "redirect": {
                "return_url": "https://rubrica.test/plan?billing=updated"
            },
        },
    }


def test_stripe_plan_change_reactivates_scheduled_subscription(monkeypatch) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    updates: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Subscription.retrieve",
        lambda _subscription_id: {"cancel_at_period_end": True},
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Subscription.modify",
        lambda subscription_id, **kwargs: updates.append(
            (subscription_id, kwargs["cancel_at_period_end"])
        ),
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.billing_portal.Session.create",
        lambda **_kwargs: SimpleNamespace(url="https://billing.stripe.test/update"),
    )

    session = StripeBillingProvider().create_portal_session(
        customer_id="cus_test",
        return_url="https://rubrica.test/plan",
        subscription_id="sub_test",
    )

    assert session.url == "https://billing.stripe.test/update"
    assert updates == [("sub_test", False)]


def test_stripe_plan_change_restores_cancellation_if_portal_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    updates: list[bool] = []
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Subscription.retrieve",
        lambda _subscription_id: {"cancel_at_period_end": True},
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Subscription.modify",
        lambda _subscription_id, **kwargs: updates.append(
            kwargs["cancel_at_period_end"]
        ),
    )

    def reject_portal(**_kwargs):
        raise RuntimeError("portal unavailable")

    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.billing_portal.Session.create",
        reject_portal,
    )

    with pytest.raises(BillingProviderError, match="could not be opened"):
        StripeBillingProvider().create_portal_session(
            customer_id="cus_test",
            return_url="https://rubrica.test/plan",
            subscription_id="sub_test",
        )

    assert updates == [False, True]
