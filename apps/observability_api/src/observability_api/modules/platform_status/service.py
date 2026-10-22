from observability_api.infrastructure.grafana_client import GrafanaClient
from observability_api.infrastructure.settings import settings
from observability_api.modules.platform_status.schemas import PlatformStatusResponse


async def get_platform_status() -> PlatformStatusResponse:
    client = GrafanaClient(
        base_url=settings.PLATFORM_GRAFANA_URL,
        timeout_seconds=settings.PLATFORM_GRAFANA_TIMEOUT_SECONDS,
        service_token=settings.PLATFORM_GRAFANA_SERVICE_TOKEN,
    )
    result = await client.status()
    return PlatformStatusResponse(
        status="available" if result.available else "unavailable",
        version=result.version,
        reason=result.reason,
    )
