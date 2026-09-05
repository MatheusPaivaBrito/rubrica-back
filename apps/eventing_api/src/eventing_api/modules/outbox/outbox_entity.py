from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from eventing_api.infrastructure.database.base import BaseEntity
from shared_kernel.time import DateTimeService


class OutboxStatus:
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class OutboxEvent(BaseEntity):
    __tablename__ = "event_outbox"
    event_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(180), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    topic: Mapped[str] = mapped_column(String(180), index=True, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(180), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default=OutboxStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def mark_published(self) -> None:
        self.status = OutboxStatus.PUBLISHED
        self.published_at = DateTimeService.utc_now()
        self.last_error = None

    def mark_failed(self, error: str) -> None:
        self.status = OutboxStatus.FAILED
        self.attempts += 1
        self.last_error = error[:2000]
