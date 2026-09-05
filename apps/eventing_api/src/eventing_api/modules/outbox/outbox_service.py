from eventing_api.infrastructure.settings import settings
from eventing_api.modules.outbox.outbox_entity import OutboxEvent
from eventing_api.modules.outbox.outbox_repository import OutboxRepository
from eventing_api.modules.outbox.outbox_schema import EventIn
from shared_kernel.time import DateTimeService


class OutboxService:
    def register(self, payload: EventIn, repository: OutboxRepository) -> OutboxEvent:
        now = DateTimeService.utc_now()
        event = OutboxEvent(
            event_id=payload.event_id,
            event_type=payload.event_type,
            version=payload.version,
            source=payload.source,
            topic=payload.topic or settings.DEFAULT_EVENT_TOPIC,
            actor_type=payload.actor.type,
            actor_id=payload.actor.id,
            payload=payload.payload,
            occurred_at=payload.occurred_at or now,
            available_at=now,
        )
        return repository.add(event)


outbox_service = OutboxService()
