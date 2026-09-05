import httpx

from core_api.infrastructure.settings import settings
from core_api.modules.billing.billing_errors import BillingProviderError
from shared_kernel.identifiers import Identifier


class AuthProvisioningClient:
    def provision_admin(self, email: str) -> Identifier:
        try:
            response = httpx.post(
                f"{settings.AUTH_API_INTERNAL_URL.rstrip('/')}/internal/auth/billing-admins",
                headers={
                    "X-Atlas-Service": "core_api",
                    "X-Atlas-Service-Key": settings.CORE_TO_AUTH_SERVICE_KEY,
                },
                json={"email": email, "role_key": "tenant_bot_admin"},
                timeout=max(settings.AUTH_INTROSPECTION_TIMEOUT_SECONDS, 5.0),
            )
            response.raise_for_status()
            return Identifier(str(response.json()["user_id"]))
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise BillingProviderError("Administrator provisioning failed") from exc


auth_provisioning_client = AuthProvisioningClient()
