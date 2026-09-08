from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventActor(BaseModel):
    type: str = "service"
    id: str = "rubrica"


class EventIn(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=1, max_length=180)
    occurred_at: datetime | None = None
    source: str = Field(min_length=1, max_length=80)
    version: int = Field(default=1, ge=1)
    topic: str | None = None
    actor: EventActor = Field(default_factory=EventActor)
    payload: dict = Field(default_factory=dict)


class OutboxRecord(BaseModel):
    event_id: UUID
    event_type: str
    version: int
    source: str
    topic: str
    actor_type: str
    actor_id: str
    payload: dict
    status: str
    attempts: int
    occurred_at: datetime
    available_at: datetime
    published_at: datetime | None = None
    last_error: str | None = None
    model_config = {"from_attributes": True}
