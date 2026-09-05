from fastapi import APIRouter

from eventing_api.infrastructure.settings import settings


router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("")
async def list_topics() -> dict[str, object]:
    return {"default": settings.DEFAULT_EVENT_TOPIC, "dead_letter": settings.DEAD_LETTER_TOPIC, "kafka_enabled": settings.EVENTING_KAFKA_ENABLED}
