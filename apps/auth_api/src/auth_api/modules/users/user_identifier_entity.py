from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from auth_api.infrastructure.database.connection import BaseEntity


class UserIdentifierEntity(BaseEntity):
    __tablename__ = "user_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "identifier_type",
            "issuing_country",
            "lookup_hmac",
            name="uq_user_identifier_lookup",
        ),
        CheckConstraint(
            "(verification_status = 'legacy' AND normalized_value_encrypted IS NULL "
            "AND lookup_hmac IS NULL) OR "
            "(verification_status <> 'legacy' AND normalized_value_encrypted IS NOT NULL "
            "AND lookup_hmac IS NOT NULL)",
            name="ck_user_identifier_protected_or_legacy",
        ),
        CheckConstraint(
            "issuing_country ~ '^[A-Z]{2}$'",
            name="ck_user_identifier_country_code",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issuing_country: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    identifier_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    normalized_value_encrypted: Mapped[str | None] = mapped_column(String(512))
    lookup_hmac: Mapped[str | None] = mapped_column(String(64), index=True)
    masked_display: Mapped[str] = mapped_column(String(96), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="format_valid", index=True
    )
    verification_method: Mapped[str | None] = mapped_column(String(48))
    key_version: Mapped[int] = mapped_column(
        nullable=False, default=1, server_default="1"
    )
