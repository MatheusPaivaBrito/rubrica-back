from core_api.infrastructure.settings import settings
from core_api.modules.billing.providers.fake_provider import FakeBillingProvider
from core_api.modules.billing.providers.protocol import BillingProvider
from core_api.modules.billing.providers.stripe_provider import StripeBillingProvider


def billing_provider() -> BillingProvider:
    if settings.BILLING_PROVIDER == "fake":
        return FakeBillingProvider()
    return StripeBillingProvider()
