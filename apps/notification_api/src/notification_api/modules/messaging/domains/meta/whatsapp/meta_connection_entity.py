from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from shared_kernel.identifiers import Identifier, new_identifier


class MetaConnectionBase(DeclarativeBase):
    pass


class MetaWhatsappConnection(MetaConnectionBase):
    __tablename__ = "meta_whatsapp_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_meta_whatsapp_connections_tenant"),
        Index(
            "uq_meta_whatsapp_connections_connected_phone",
            "phone_number_id",
            unique=True,
            postgresql_where=text("status = 'connected'"),
        ),
    )

    id: Mapped[Identifier] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_identifier
    )
    tenant_id: Mapped[Identifier] = mapped_column(UUID(as_uuid=True), nullable=False)
    waba_id: Mapped[str] = mapped_column(String(80), nullable=False)
    phone_number_id: Mapped[str] = mapped_column(String(80), nullable=False)
    display_phone_number: Mapped[str | None] = mapped_column(String(40))
    verified_name: Mapped[str | None] = mapped_column(String(255))
    quality_rating: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="connected")
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
