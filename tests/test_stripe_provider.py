from types import SimpleNamespace

import pytest

from core_api.modules.billing.providers.protocol import (
    BillingProviderError,
    CheckoutConflictError,
    InvalidWebhookSignatureError,
)
from core_api.modules.billing.providers.stripe_provider import StripeBillingProvider


@pytest.fixture(autouse=True)
def empty_checkout_history(monkeypatch):
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.checkout.Session.list",
        lambda **_: SimpleNamespace(auto_paging_iter=lambda: iter(())),
    )


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
        "price_id": "price_jpy",
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
    assert captured["adaptive_pricing"] == {"enabled": False}
    assert captured["tax_id_collection"] == {"enabled": True}
    assert captured["customer_update"] == {"name": "auto", "address": "auto"}


def test_stripe_provider_translates_checkout_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.checkout.Session.create",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("stripe rejected checkout")),
    )

    with pytest.raises(BillingProviderError, match="checkout could not be opened"):
        StripeBillingProvider().create_checkout_session(
            customer_id="cus_test",
            price_id="price_professional",
            product_code="rubrica_intermediate",
            tenant_id="019c-tenant",
            success_url="https://rubrica.test/plan?checkout=success",
            cancel_url="https://rubrica.test/plan?checkout=cancelled",
        )


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


def test_stripe_portal_confirms_the_selected_price(monkeypatch) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Subscription.retrieve",
        lambda _subscription_id: {
            "cancel_at_period_end": False,
            "items": {"data": [{"id": "si_test"}]},
        },
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.billing_portal.Session.create",
        lambda **kwargs: (captured.update(kwargs) or SimpleNamespace(url="https://billing.stripe.test/confirm")),
    )

    StripeBillingProvider().create_portal_session(
        customer_id="cus_test",
        return_url="https://rubrica.test/plan",
        subscription_id="sub_test",
        price_id="price_team_annual",
    )

    assert captured["flow_data"]["type"] == "subscription_update_confirm"
    assert captured["flow_data"]["subscription_update_confirm"]["items"] == [
        {"id": "si_test", "price": "price_team_annual", "quantity": 1}
    ]


@pytest.mark.parametrize("cancellation", [{"cancel_at_period_end": True}, {"cancel_at": 1_800_000_000}])
def test_stripe_plan_change_does_not_revoke_a_scheduled_cancellation(monkeypatch, cancellation) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    calls = []
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Subscription.retrieve",
        lambda _subscription_id: cancellation | {"items": {"data": [{"id": "si_test"}]}},
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Subscription.modify",
        lambda *args, **kwargs: calls.append("subscription update"),
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.billing_portal.Session.create",
        lambda **_kwargs: calls.append("portal session") or SimpleNamespace(url="https://billing.stripe.test/update"),
    )

    with pytest.raises(CheckoutConflictError, match="Resume the subscription"):
        StripeBillingProvider().create_portal_session(
            customer_id="cus_test", return_url="https://rubrica.test/plan",
            subscription_id="sub_test", price_id="price_annual",
        )
    assert calls == []


def test_stripe_plan_change_translates_a_provider_portal_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    updates: list[bool] = []
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Subscription.retrieve",
        lambda _subscription_id: {"cancel_at_period_end": False},
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

    assert updates == []


@pytest.mark.parametrize("prices", [("price_target",), ("price_base", "price_add_on")])
def test_stripe_portal_rejects_same_price_or_multi_item_change(monkeypatch, prices):
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY",
        "sk_test_example",
    )
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.Subscription.retrieve",
        lambda _id: {"items": {"data": [
            {"id": f"si_{i}", "price": {"id": price}} for i, price in enumerate(prices)
        ]}},
    )
    sessions = []
    monkeypatch.setattr(
        "core_api.modules.billing.providers.stripe_provider.stripe.billing_portal.Session.create",
        lambda **kwargs: sessions.append(kwargs),
    )

    with pytest.raises(CheckoutConflictError):
        StripeBillingProvider().create_portal_session(
            customer_id="cus_test", return_url="https://rubrica.test/plan",
            subscription_id="sub_test", price_id="price_target",
        )
    assert not sessions


@pytest.mark.parametrize(("matching", "adaptive"), [(True, False), (False, False), (True, True)])
def test_checkout_reuses_only_the_requested_fixed_price(monkeypatch, matching, adaptive):
    from core_api.modules.billing.providers.stripe_provider import stripe

    monkeypatch.setattr("core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY", "sk_test")
    existing = stripe.StripeObject.construct_from({
        "id": "cs_old", "client_reference_id": "tenant", "mode": "subscription",
        "status": "open", "payment_status": "unpaid", "url": "https://stripe.test/old",
        "adaptive_pricing": {"enabled": adaptive},
    }, None)
    expired = []
    created = []
    monkeypatch.setattr(stripe.checkout.Session, "list", lambda **_: SimpleNamespace(auto_paging_iter=lambda: iter([existing])))
    monkeypatch.setattr(stripe.checkout.Session, "list_line_items", lambda *_args, **_kwargs: {
        "data": [{"quantity": 1, "price": {"id": "price_brl" if matching else "price_usd"}}],
    })
    monkeypatch.setattr(stripe.checkout.Session, "expire", expired.append)

    def create(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(url="https://stripe.test/new")

    monkeypatch.setattr(stripe.checkout.Session, "create", create)
    result = StripeBillingProvider().create_checkout_session(
        customer_id="cus_test", tenant_id="tenant", price_id="price_brl",
        product_code="rubrica_base", success_url="https://rubrica.test/success",
        cancel_url="https://rubrica.test/cancel",
    )
    if matching and not adaptive:
        assert result.url == "https://stripe.test/old"
        assert not expired and not created
    else:
        assert result.url == "https://stripe.test/new"
        assert expired == ["cs_old"]
        assert created[0]["idempotency_key"].startswith("rubrica-checkout-")


@pytest.mark.parametrize(("status", "allow_checkout"), [
    ("active", False), ("trialing", False), ("incomplete", False), ("past_due", False),
    ("unpaid", False), ("paused", False), ("incomplete_expired", True), ("canceled", True),
])
def test_checkout_checks_completed_session_before_creating_a_second_subscription(monkeypatch, status, allow_checkout):
    from core_api.modules.billing.providers.stripe_provider import stripe

    session = stripe.StripeObject.construct_from({
        "id": "cs_complete", "client_reference_id": "tenant", "mode": "subscription",
        "status": "complete", "subscription": "sub_existing", "payment_status": "paid",
    }, None)
    monkeypatch.setattr(stripe.checkout.Session, "list", lambda **_: SimpleNamespace(auto_paging_iter=lambda: iter([session])))
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda _id: {"status": status})
    if allow_checkout:
        assert StripeBillingProvider._reconcile_checkout("cus_test", "tenant", "price_brl") == (None, session.id)
    else:
        with pytest.raises(CheckoutConflictError, match="existing subscription"):
            StripeBillingProvider._reconcile_checkout("cus_test", "tenant", "price_brl")


def test_checkout_stops_if_another_tab_finishes_payment_during_expiration(monkeypatch):
    from core_api.modules.billing.providers.stripe_provider import stripe

    monkeypatch.setattr("core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY", "sk_test")
    session = stripe.StripeObject.construct_from({
        "id": "cs_old", "client_reference_id": "tenant", "mode": "subscription",
        "status": "open", "payment_status": "unpaid",
    }, None)
    monkeypatch.setattr(stripe.checkout.Session, "list", lambda **_: SimpleNamespace(auto_paging_iter=lambda: iter([session])))
    monkeypatch.setattr(stripe.checkout.Session, "list_line_items", lambda *_args, **_kwargs: {"data": []})

    def checkout_already_completed(_session_id):
        raise stripe.InvalidRequestError("Session is complete", "status")

    def unexpected_checkout(**_kwargs):
        pytest.fail("A second checkout was created while the first was completing")

    monkeypatch.setattr(stripe.checkout.Session, "expire", checkout_already_completed)
    monkeypatch.setattr(stripe.checkout.Session, "create", unexpected_checkout)
    with pytest.raises(CheckoutConflictError, match="Checkout changed"):
        StripeBillingProvider().create_checkout_session(
            customer_id="cus_test", tenant_id="tenant", price_id="price_brl",
            product_code="rubrica_base", success_url="https://rubrica.test/success",
            cancel_url="https://rubrica.test/cancel",
        )


@pytest.mark.parametrize("stripe_state", ["pending", "paid", "not_received"])
def test_lost_seat_change_response_never_creates_a_second_proration(monkeypatch, stripe_state):
    from core_api.modules.billing.providers.stripe_provider import stripe

    monkeypatch.setattr("core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY", "sk_test")
    base_item = {"id": "si_base", "price": {"id": "price_base", "recurring": {"interval": "month"}}, "quantity": 1}
    target = [base_item, {"id": "si_seat", "price": {"id": "price_seat"}, "quantity": 1}]
    subscription = {"items": {"data": [base_item]}, "latest_invoice": {"id": "in_previous"}, "status": "active"}
    calls = []

    def modify(_id, **params):
        calls.append(params)
        if len(calls) > 1:
            return {"latest_invoice": {"id": "in_proration"}}
        if stripe_state != "not_received":
            subscription["latest_invoice"] = {
                "id": "in_proration", "billing_reason": "subscription_update",
                "status": "paid" if stripe_state == "paid" else "open",
            }
        if stripe_state == "pending":
            subscription["pending_update"] = {"subscription_items": target}
        elif stripe_state == "paid":
            subscription["items"]["data"] = target
        raise TimeoutError("The response was not received")

    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda _id, **_params: subscription)
    monkeypatch.setattr(stripe.Subscription, "modify", modify)
    provider = StripeBillingProvider()
    args = dict(subscription_id="sub_test", product_code="rubrica_intermediate", base_price_id="price_base",
                billing_interval="month", seat_price_id="price_seat", seat_price_ids=frozenset({"price_seat"}),
                additional_seats=1)
    with pytest.raises(BillingProviderError):
        provider.update_subscription_seats(**args)
    assert provider.update_subscription_seats(**args).invoice_id == "in_proration"
    if stripe_state == "not_received":
        assert len(calls) == 2
        assert calls[0]["idempotency_key"] == calls[1]["idempotency_key"]
    else:
        assert len(calls) == 1


@pytest.mark.parametrize("conflict", ["cancel_scheduled", "different_pending", "unexpected_items", "different_interval", "subscription_past_due"])
def test_seat_change_preserves_existing_stripe_state(monkeypatch, conflict):
    from core_api.modules.billing.providers.stripe_provider import stripe

    monkeypatch.setattr("core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY", "sk_test")
    base_item = {"id": "si_base", "price": {"id": "price_base", "recurring": {"interval": "month"}}, "quantity": 1}
    subscription = {"items": {"data": [base_item]}, "latest_invoice": {"id": "in_previous"}, "status": "active"}
    if conflict == "cancel_scheduled":
        subscription["cancel_at_period_end"] = True
    elif conflict == "different_pending":
        subscription["pending_update"] = {"subscription_items": [
            base_item, {"id": "si_seat", "price": {"id": "price_seat"}, "quantity": 2},
        ]}
    elif conflict == "unexpected_items":
        subscription["items"]["data"].append({"id": "si_other", "price": {"id": "price_other"}, "quantity": 1})
    elif conflict == "different_interval":
        base_item["price"]["recurring"]["interval"] = "year"
    else:
        subscription["status"] = "past_due"

    def unexpected_charge(*_args, **_kwargs):
        pytest.fail("The seat change modified the Stripe subscription")

    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda _id, **_params: subscription)
    monkeypatch.setattr(stripe.Subscription, "modify", unexpected_charge)
    with pytest.raises(CheckoutConflictError):
        StripeBillingProvider().update_subscription_seats(
            subscription_id="sub_test", product_code="rubrica_intermediate", base_price_id="price_base",
            billing_interval="month", seat_price_id="price_seat", seat_price_ids=frozenset({"price_seat"}),
            additional_seats=1,
        )


def test_checkout_retry_after_timeout_uses_same_idempotency_key(monkeypatch):
    from core_api.modules.billing.providers.stripe_provider import stripe

    monkeypatch.setattr("core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY", "sk_test")
    keys = []

    def create(**kwargs):
        keys.append(kwargs["idempotency_key"])
        if len(keys) == 1:
            raise TimeoutError
        return SimpleNamespace(url="https://stripe.test/existing")

    monkeypatch.setattr(stripe.checkout.Session, "create", create)
    provider = StripeBillingProvider()
    parameters = {
        "customer_id": "cus_test", "tenant_id": "tenant", "price_id": "price_brl",
        "product_code": "rubrica_base", "success_url": "https://rubrica.test/success",
        "cancel_url": "https://rubrica.test/cancel",
    }
    with pytest.raises(BillingProviderError):
        provider.create_checkout_session(**parameters)
    assert provider.create_checkout_session(**parameters).url == "https://stripe.test/existing"
    assert keys[0] == keys[1]


@pytest.mark.parametrize("has_payment", [False, True])
def test_currency_recovery_expires_only_abandoned_sessions_for_the_same_workspace(monkeypatch, has_payment):
    from core_api.modules.billing.providers.protocol import CheckoutConflictError
    from core_api.modules.billing.providers.stripe_provider import stripe

    def open_session(session_id, workspace):
        return stripe.StripeObject.construct_from({
            "id": session_id, "client_reference_id": workspace, "mode": "subscription",
            "status": "open", "payment_status": "unpaid", "url": "https://stripe.test/session",
        }, None)

    sessions = [open_session(f"cs_usd{index}", "tenant-a") for index in range(3)]
    sessions.append(open_session("cs_unrelated", "tenant-b"))
    if has_payment:
        sessions.insert(0, stripe.StripeObject.construct_from({
            "id": "cs_paid", "client_reference_id": "tenant-a", "mode": "subscription",
            "status": "complete", "payment_status": "paid", "invoice": "in_test",
        }, None))
    expired = []
    created = []

    def list_customer_sessions(*, customer):
        assert customer == "cus_test"
        return SimpleNamespace(auto_paging_iter=lambda: iter(sessions))

    def create_brl(**kwargs):
        assert kwargs["line_items"] == [{"price": "price_brl", "quantity": 1}]
        assert expired == ["cs_usd0", "cs_usd1", "cs_usd2"]
        created.append(kwargs)
        return SimpleNamespace(url="https://stripe.test/brl")

    monkeypatch.setattr("core_api.modules.billing.providers.stripe_provider.settings.STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(stripe.checkout.Session, "list", list_customer_sessions)
    monkeypatch.setattr(stripe.checkout.Session, "list_line_items", lambda *_args, **_kwargs: {
        "data": [{"quantity": 1, "price": {"id": "price_usd", "currency": "usd"}}],
    })
    monkeypatch.setattr(stripe.checkout.Session, "expire", expired.append)
    monkeypatch.setattr(stripe.checkout.Session, "create", create_brl)

    def checkout():
        return StripeBillingProvider().create_checkout_session(
            customer_id="cus_test", tenant_id="tenant-a", price_id="price_brl",
            product_code="rubrica_base", success_url="https://rubrica.test/success",
            cancel_url="https://rubrica.test/cancel",
        )

    if has_payment:
        with pytest.raises(CheckoutConflictError, match="payment is already in progress"):
            checkout()
        assert not expired and not created
    else:
        assert checkout().url == "https://stripe.test/brl"
        assert len(created) == 1


@pytest.mark.parametrize("blocking_field", ["invoice", "subscription", "payment_status"])
def test_checkout_reconciliation_leaves_every_session_intact_when_payment_is_in_flight(monkeypatch, blocking_field):
    from core_api.modules.billing.providers.protocol import CheckoutConflictError
    from core_api.modules.billing.providers.stripe_provider import stripe

    base = {"client_reference_id": "tenant", "mode": "subscription", "status": "open", "payment_status": "unpaid"}
    blocking_value = "paid" if blocking_field == "payment_status" else "object_test"
    sessions = [
        stripe.StripeObject.construct_from(base | {"id": "cs_old"}, None),
        stripe.StripeObject.construct_from(base | {"id": "cs_pending", blocking_field: blocking_value}, None),
    ]
    monkeypatch.setattr(stripe.checkout.Session, "list", lambda **_: SimpleNamespace(auto_paging_iter=lambda: iter(sessions)))
    monkeypatch.setattr(stripe.checkout.Session, "list_line_items", lambda *_args, **_kwargs: {"data": []})

    def unexpected_expiration(*_args):
        pytest.fail("Checkout reconciliation modified a session while payment was in flight")

    monkeypatch.setattr(stripe.checkout.Session, "expire", unexpected_expiration)
    with pytest.raises(CheckoutConflictError, match="payment is already in progress"):
        StripeBillingProvider._reconcile_checkout("cus_test", "tenant", "price_brl")
