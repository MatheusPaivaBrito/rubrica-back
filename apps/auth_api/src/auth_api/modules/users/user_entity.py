from datetime import datetime
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from auth_api.infrastructure.database.connection import BaseEntity


class UserEntity(BaseEntity):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    public_slug: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False, default=lambda: token_urlsafe(18)
    )
    name: Mapped[str | None] = mapped_column(String(180), index=True)
    preferred_locale: Mapped[str] = mapped_column(
        String(10), default="en", server_default="en", nullable=False, index=True
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    mfa_exempt: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    mfa_secret_ciphertext: Mapped[str | None] = mapped_column(String(512))
    mfa_pending_secret_ciphertext: Mapped[str | None] = mapped_column(String(512))
    mfa_last_used_step: Mapped[int | None] = mapped_column(Integer)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_version: Mapped[int] = mapped_column(default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AccountTokenEntity(BaseEntity):
    __tablename__ = "account_tokens"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MfaRecoveryCodeEntity(BaseEntity):
    __tablename__ = "mfa_recovery_codes"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MfaSecurityEventEntity(BaseEntity):
    __tablename__ = "mfa_security_events"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metadata_sanitized: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
