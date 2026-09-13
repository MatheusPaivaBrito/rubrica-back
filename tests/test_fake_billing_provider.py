from core_api.modules.billing.providers.fake_provider import FakeBillingProvider


def test_fake_billing_provider_keeps_checkout_local() -> None:
    provider = FakeBillingProvider()
    customer = provider.create_customer(email="demo@example.com", name="Demo", metadata={})

    checkout = provider.create_checkout_session(
        customer_id=customer.id,
        price_id="price_fake",
        tenant_id="tenant_fake",
        success_url="http://localhost:8080/billing?checkout=success",
        cancel_url="http://localhost:8080/billing?checkout=cancelled",
    )

    assert customer.id.startswith("fake_customer_")
    assert checkout.url == "http://localhost:8080/billing?checkout=success"
