from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eventing_api.modules.outbox.outbox_entity import OutboxEvent, OutboxStatus


class OutboxRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, event: OutboxEvent) -> OutboxEvent:
        self.session.add(event)
        self.session.flush()
        self.session.refresh(event)
        return event

    def get(self, event_id: str) -> OutboxEvent | None:
        statement = select(OutboxEvent).where(OutboxEvent.event_id == event_id)
        return self.session.execute(statement).scalar_one_or_none()

    def list(
        self,
        *,
        status: str | None = None,
        event_type_prefix: str | None = None,
        limit: int = 50,
    ) -> list[OutboxEvent]:
        statement = select(OutboxEvent)
        if status:
            statement = statement.where(OutboxEvent.status == status)
        if event_type_prefix:
            statement = statement.where(
                OutboxEvent.event_type.like(f"{event_type_prefix}.%")
            )
        statement = statement.order_by(OutboxEvent.created_at.desc()).limit(limit)
        return list(self.session.execute(statement).scalars())

    def status_counts(
        self,
        *,
        event_type_prefix: str | None = None,
    ) -> dict[str, int]:
        statement = select(
            OutboxEvent.status,
            func.count(OutboxEvent.id),
        ).group_by(OutboxEvent.status)
        if event_type_prefix:
            statement = statement.where(
                OutboxEvent.event_type.like(f"{event_type_prefix}.%")
            )
        return {
            status: count
            for status, count in self.session.execute(statement).all()
        }

    def event_type_counts(
        self,
        *,
        event_type_prefix: str | None = None,
    ) -> dict[str, int]:
        statement = select(
            OutboxEvent.event_type,
            func.count(OutboxEvent.id),
        ).group_by(OutboxEvent.event_type)
        if event_type_prefix:
            statement = statement.where(
                OutboxEvent.event_type.like(f"{event_type_prefix}.%")
            )
        return {
            event_type: count
            for event_type, count in self.session.execute(statement).all()
        }

    def pending(self, *, limit: int = 100) -> list[OutboxEvent]:
        statement = select(OutboxEvent).where(OutboxEvent.status == OutboxStatus.PENDING).order_by(OutboxEvent.available_at.asc()).limit(limit)
        return list(self.session.execute(statement).scalars())
