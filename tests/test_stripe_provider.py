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


def test_stripe_provider_builds_checkout_with_tenant_metadata(monkeypatch) -> None:
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
        product_code="rubrica_intermediate",
        tenant_id="019c-tenant",
        success_url="https://rubrica.test/plan?checkout=success",
        cancel_url="https://rubrica.test/plan?checkout=cancelled",
    )

    assert session.url == "https://checkout.stripe.test/session"
    assert captured["client_reference_id"] == "019c-tenant"
    assert captured["metadata"] == {
        "tenant_id": "019c-tenant",
        "product_code": "rubrica_intermediate",
    }
    assert captured["subscription_data"] == {
        "metadata": {
            "tenant_id": "019c-tenant",
            "product_code": "rubrica_intermediate",
        }
    }
    assert captured["line_items"] == [{"price": "price_jpy", "quantity": 1}]


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

    session = StripeBillingProvider().create_portal_session(
        customer_id="cus_test",
        return_url="https://rubrica.test/plan",
        subscription_id="sub_test",
    )

    assert session.url == "https://billing.stripe.test/session"
    assert captured["flow_data"] == {
        "type": "subscription_update",
        "subscription_update": {"subscription": "sub_test"},
        "after_completion": {"type": "portal_homepage"},
    }
