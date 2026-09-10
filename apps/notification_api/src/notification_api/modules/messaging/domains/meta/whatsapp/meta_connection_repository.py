from __future__ import annotations

from functools import lru_cache

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from notification_api.infrastructure.settings import settings
from notification_api.modules.messaging.domains.meta.whatsapp.meta_connection_entity import (
    MetaWhatsappConnection,
)
from shared_kernel.identifiers import Identifier


class MetaConnectionRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self._engine = create_engine(
            database_url or settings.DATABASE_URL,
            pool_pre_ping=True,
        )

    def get_by_tenant(self, tenant_id: Identifier) -> MetaWhatsappConnection | None:
        with Session(self._engine) as session:
            return session.scalar(
                select(MetaWhatsappConnection).where(
                    MetaWhatsappConnection.tenant_id == tenant_id
                )
            )

    def get_connected_by_phone_number_id(
        self,
        phone_number_id: str,
    ) -> MetaWhatsappConnection | None:
        with Session(self._engine) as session:
            return session.scalar(
                select(MetaWhatsappConnection).where(
                    MetaWhatsappConnection.phone_number_id == phone_number_id,
                    MetaWhatsappConnection.status == "connected",
                )
            )

    def save(self, connection: MetaWhatsappConnection) -> MetaWhatsappConnection:
        with Session(self._engine) as session:
            merged = session.merge(connection)
            session.commit()
            session.refresh(merged)
            session.expunge(merged)
            return merged

    def assign(
        self,
        connection: MetaWhatsappConnection,
        *,
        confirm_reassignment: bool,
    ) -> MetaWhatsappConnection:
        with Session(self._engine) as session:
            conflicting = session.scalar(
                select(MetaWhatsappConnection)
                .where(
                    MetaWhatsappConnection.phone_number_id == connection.phone_number_id,
                    MetaWhatsappConnection.tenant_id != connection.tenant_id,
                    MetaWhatsappConnection.status == "connected",
                )
                .with_for_update()
            )
            if conflicting is not None:
                if not confirm_reassignment:
                    raise MetaPhoneNumberConflictError()
                conflicting.status = "disconnected"
                conflicting.disconnected_at = datetime.now(UTC)
            merged = session.merge(connection)
            session.commit()
            session.refresh(merged)
            session.expunge(merged)
            return merged


class MetaPhoneNumberConflictError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_meta_connection_repository() -> MetaConnectionRepository:
    return MetaConnectionRepository()
