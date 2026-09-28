from uuid import UUID

import httpx

from auth_api.infrastructure.settings import settings
from auth_api.modules.accounts.account_schema import PublicRegistration


class TenantProvisioningError(RuntimeError):
    pass


def provision_account_tenant(payload: PublicRegistration, user_id: UUID | None = None) -> None:
    try:
        body = {
            "owner_email": payload.email.strip().lower(),
            "name": payload.name.strip(),
            "default_locale": payload.preferred_locale,
            "country_code": payload.identity_document_country,
        }
        if user_id is not None:
            body["owner_user_id"] = str(user_id)
        response = httpx.post(
            f"{settings.CORE_API_URL.rstrip('/')}/internal/tenants/provision",
            json=body,
            headers={
                "X-Rubrica-Service": "auth_api",
                "X-Rubrica-Service-Key": settings.CORE_INTERNAL_SERVICE_KEY,
            },
            timeout=5.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TenantProvisioningError("Tenant provisioning is unavailable") from exc
