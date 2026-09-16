from dataclasses import dataclass

import httpx

from core_api.infrastructure.settings import settings


@dataclass(frozen=True)
class IdentitySummary:
    identifier_type: str | None = None
    issuing_country: str | None = None
    masked_display: str | None = None


def identity_summary(email: str) -> IdentitySummary:
    try:
        response = httpx.get(
            f"{settings.AUTH_API_URL.rstrip('/')}/users/internal/identity-summary",
            params={"email": email.strip().lower()},
            headers={
                "X-Rubrica-Service": "core_api",
                "X-Rubrica-Service-Key": settings.CORE_INTERNAL_SERVICE_KEY,
            },
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
        return IdentitySummary(
            identifier_type=payload.get("identifier_type"),
            issuing_country=payload.get("issuing_country"),
            masked_display=payload.get("masked_display"),
        )
    except (httpx.HTTPError, ValueError, AttributeError):
        return IdentitySummary()
