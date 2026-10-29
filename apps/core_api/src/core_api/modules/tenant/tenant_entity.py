from uuid import UUID

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from core_api.infrastructure.database.connection import BaseEntity


class TenantEntity(BaseEntity):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    default_locale: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en", server_default="en"
    )
    country_code: Mapped[str | None] = mapped_column(String(2))
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default="USD"
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="personal", server_default="personal", index=True
    )
    legal_name: Mapped[str | None] = mapped_column(String(240))
    registration_country: Mapped[str | None] = mapped_column(String(2))
    registration_type: Mapped[str | None] = mapped_column(String(32))
    registration_value_encrypted: Mapped[str | None] = mapped_column(String(512))
    registration_lookup_hmac: Mapped[str | None] = mapped_column(String(64), index=True)
    registration_masked: Mapped[str | None] = mapped_column(String(40))
    registration_verification_status: Mapped[str | None] = mapped_column(String(32))
    registration_source: Mapped[str | None] = mapped_column(String(32))
    registration_provider_reference: Mapped[str | None] = mapped_column(String(255))
    stamp_customization: Mapped[dict[str, object] | None] = mapped_column(JSON)


class TenantMemberEntity(BaseEntity):
    __tablename__ = "tenant_members"
    __table_args__ = (
        UniqueConstraint("tenant_id", "auth_user_id", name="uq_tenant_member_identity"),
        Index(
            "uq_tenant_member_user_uuid",
            "tenant_id",
            "auth_user_uuid",
            unique=True,
            postgresql_where=text("auth_user_uuid IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    auth_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    auth_user_uuid: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="member", index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active", index=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantSeatRosterEntity(BaseEntity):
    __tablename__ = "tenant_seat_rosters"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "cycle_starts_at", name="uq_tenant_seat_roster_cycle"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cycle_starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    seat_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    member_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="scheduled", server_default="scheduled"
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
