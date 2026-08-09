from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class EventActor:
    type: str
    id: str


@dataclass(frozen=True)
class EventEnvelope:
    event_type: str
    source: str
    actor: EventActor
    payload: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "source": self.source,
            "version": self.version,
            "actor": {"type": self.actor.type, "id": self.actor.id},
            "payload": self.payload,
        }
