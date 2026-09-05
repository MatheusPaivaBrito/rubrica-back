from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_errors import BillingConfigurationError

from .base import BillingProvider
from .fake import FakeBillingProvider
from .mercado_pago import MercadoPagoProvider


def billing_provider() -> BillingProvider:
    provider = settings.BILLING_PROVIDER.strip().lower()
    if provider == "fake":
        return FakeBillingProvider()
    if provider == "mercado_pago":
        return MercadoPagoProvider(
            access_token=settings.MERCADO_PAGO_ACCESS_TOKEN,
            webhook_secret=settings.MERCADO_PAGO_WEBHOOK_SECRET,
            base_url=settings.MERCADO_PAGO_API_BASE_URL,
            timeout_seconds=settings.MERCADO_PAGO_TIMEOUT_SECONDS,
        )
    raise BillingConfigurationError(f"Unsupported billing provider: {provider}")
