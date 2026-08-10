from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core_api.infrastructure.database.connection import BaseEntity


class SignatureRequestEntity(BaseEntity):
    __tablename__ = "signature_requests"

    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), index=True)
    document_version: Mapped[int]
    document_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(255), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signing_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)


class SignerEntity(BaseEntity):
    __tablename__ = "signers"
    __table_args__ = (UniqueConstraint("signature_request_id", "auth_user_id"),)

    signature_request_id: Mapped[int] = mapped_column(ForeignKey("signature_requests.id", ondelete="RESTRICT"), index=True)
    auth_user_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(180))
    email: Mapped[str] = mapped_column(String(254), index=True)
    signing_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    link_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignatureEntity(BaseEntity):
    __tablename__ = "signatures"
    __table_args__ = (
        UniqueConstraint("signature_request_id", "signer_id"),
        UniqueConstraint("signature_request_id", "auth_user_id"),
    )

    signature_request_id: Mapped[int] = mapped_column(ForeignKey("signature_requests.id", ondelete="RESTRICT"), index=True)
    signer_id: Mapped[int] = mapped_column(ForeignKey("signers.id", ondelete="RESTRICT"), index=True)
    auth_user_id: Mapped[str] = mapped_column(String(255), index=True)
    document_sha256: Mapped[str] = mapped_column(String(64))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON)


class AuditEventEntity(BaseEntity):
    __tablename__ = "audit_events"

    signature_request_id: Mapped[int | None] = mapped_column(ForeignKey("signature_requests.id", ondelete="RESTRICT"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor_type: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str] = mapped_column(String(255), index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    metadata_sanitized: Mapped[dict[str, object]] = mapped_column(JSON)
