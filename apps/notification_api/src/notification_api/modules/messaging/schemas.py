from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DeliveryPolicy(BaseModel):
    mode: Literal["transient", "tracked", "reliable"] | None = None
    retention_seconds: int | None = Field(default=None, ge=60, le=2592000)


class DeliveryAccepted(BaseModel):
    delivery_id: UUID
    channel: str
    recipient: str
    provider: str
    status: str
    delivery_store: str
    delivery_policy: Literal["transient", "tracked", "reliable"]
    persisted: bool
    payload_stored: bool
    retention_seconds: int | None
    payload: dict | None
    event: dict | None = None
