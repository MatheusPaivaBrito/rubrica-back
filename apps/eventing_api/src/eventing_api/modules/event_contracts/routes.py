from fastapi import APIRouter

from eventing_api.infrastructure.settings import settings


router = APIRouter(prefix="/event-contracts", tags=["event contracts"])


@router.get("")
async def list_event_contracts() -> dict[str, object]:
    return {"contracts": ["contracts/events/example/example-event.v1.schema.json"], "default_topic": settings.DEFAULT_EVENT_TOPIC, "dead_letter_topic": settings.DEAD_LETTER_TOPIC}
