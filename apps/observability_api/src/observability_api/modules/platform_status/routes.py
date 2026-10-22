from fastapi import APIRouter, Header, HTTPException

from observability_api.modules.platform_status.schemas import PlatformStatusResponse
from observability_api.modules.platform_status.service import get_platform_status
from observability_api.infrastructure.settings import settings
from shared_kernel.security.service_tokens import verify_service_token


router = APIRouter(prefix="/internal/observability", tags=["observability"])


@router.get("/platform/status", response_model=PlatformStatusResponse)
async def platform_status(
    x_rubrica_service_key: str | None = Header(default=None, alias="X-Rubrica-Service-Key"),
) -> PlatformStatusResponse:
    if (
        not settings.OBSERVABILITY_INTERNAL_SERVICE_KEY
        or not verify_service_token(
            x_rubrica_service_key or "", settings.OBSERVABILITY_INTERNAL_SERVICE_KEY
        )
    ):
        raise HTTPException(status_code=403, detail="Invalid internal service credentials")
    return await get_platform_status()
