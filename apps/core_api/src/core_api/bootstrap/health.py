from fastapi import APIRouter
from pydantic import BaseModel

from core_api.infrastructure.settings import settings


router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.SERVICE_NAME,
        environment=settings.ENVIRONMENT,
    )
