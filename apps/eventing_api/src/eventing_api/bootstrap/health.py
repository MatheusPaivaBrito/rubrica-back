from fastapi import APIRouter

from eventing_api.infrastructure.settings import settings


router = APIRouter(tags=["system"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.SERVICE_NAME, "environment": settings.ENVIRONMENT}
