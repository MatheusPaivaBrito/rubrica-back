from observability_api.modules.platform_publish.ensure import ensure
from observability_api.modules.platform_status.schemas import PlatformStatusResponse


async def get_platform_status() -> PlatformStatusResponse:
    result = await ensure()
    return PlatformStatusResponse(status="available" if result["operational"] else "unavailable",
                                  version="2" if result["authorized"] else None, reason=result["reason"])
