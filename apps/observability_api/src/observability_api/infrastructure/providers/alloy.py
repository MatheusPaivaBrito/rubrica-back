from observability_api.infrastructure.providers.http import provider_status
from observability_api.infrastructure.settings import settings


def alloy_status() -> dict:
    if not settings.ALLOY_ENABLED:
        return {"name": "alloy", "status": "disabled", "url": settings.ALLOY_READY_URL}
    return provider_status("alloy", settings.ALLOY_READY_URL, expect_json=False)
