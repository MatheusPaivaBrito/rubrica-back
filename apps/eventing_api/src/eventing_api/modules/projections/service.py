from datetime import datetime

from eventing_api.modules.outbox.outbox_repository import OutboxRepository


class ProjectionService:
    def event_family(
        self,
        repository: OutboxRepository,
        *,
        event_type_prefix: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        events = repository.list(
            event_type_prefix=event_type_prefix,
            limit=limit,
        )
        latest_events: list[dict[str, str | datetime]] = [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "source": event.source,
                "status": event.status,
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "occurred_at": event.occurred_at,
            }
            for event in events
        ]
        counts_by_event_type = repository.event_type_counts(
            event_type_prefix=event_type_prefix,
        )
        return {
            "family": event_type_prefix or "all",
            "total": sum(counts_by_event_type.values()),
            "counts_by_event_type": counts_by_event_type,
            "counts_by_status": repository.status_counts(
                event_type_prefix=event_type_prefix,
            ),
            "latest_events": latest_events,
        }


projection_service = ProjectionService()
