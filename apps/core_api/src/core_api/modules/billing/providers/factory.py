from core_api.modules.billing.providers.protocol import BillingProvider
from core_api.modules.billing.providers.stripe_provider import StripeBillingProvider


def billing_provider() -> BillingProvider:
    return StripeBillingProvider()
