from uuid import UUID
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from core_api.infrastructure.database.connection import BaseEntity


class EnterpriseIntegration(BaseEntity):
    __tablename__ = "enterprise_integrations"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)


class EnterpriseCompartment(BaseEntity):
    __tablename__ = "enterprise_compartments"

    integration_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("enterprise_integrations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)


class EnterpriseDocument(BaseEntity):
    """Separate intake prevents interactive document routes exposing API uploads."""
    __tablename__ = "enterprise_documents"
    __table_args__ = (UniqueConstraint("compartment_id", "idempotency_key", name="uq_enterprise_upload_idempotency"),)

    compartment_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_compartments.id", ondelete="RESTRICT"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(120), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    token_public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="quarantined")
    storage_namespace: Mapped[str] = mapped_column(String(24), nullable=False, default="isolated-v1", server_default="legacy")
    rubrica_copy_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnterpriseProvider(BaseEntity):
    __tablename__ = "enterprise_providers"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "sandbox", name="uq_enterprise_provider"),)

    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    encrypted_configuration: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="configured_unverified")


class EnterpriseRequest(BaseEntity):
    __tablename__ = "enterprise_requests"
    __table_args__ = (UniqueConstraint("compartment_id", "idempotency_key", name="uq_enterprise_request_idempotency"),)

    compartment_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_compartments.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_documents.id", ondelete="RESTRICT"), nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signers: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_public_id: Mapped[str] = mapped_column(String(32), nullable=False)


class EnterpriseSigningSession(BaseEntity):
    __tablename__ = "enterprise_signing_sessions"
    __table_args__ = (UniqueConstraint("request_id", "signer_id", name="uq_enterprise_signer_session"),)

    request_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_requests.id", ondelete="RESTRICT"), nullable=False)
    signer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnterpriseSignature(BaseEntity):
    __tablename__ = "enterprise_signatures"
    __table_args__ = (UniqueConstraint("request_id", "signer_id", name="uq_enterprise_signature_signer"),)

    request_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_requests.id", ondelete="RESTRICT"), nullable=False)
    signer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_hmac: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider_evidence: Mapped[dict | None] = mapped_column(JSON)
    storage_namespace: Mapped[str] = mapped_column(String(24), nullable=False, default="isolated-v1", server_default="legacy")
    rubrica_copy_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnterpriseAuthorization(BaseEntity):
    __tablename__ = "enterprise_authorizations"

    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_signing_sessions.id", ondelete="RESTRICT"), nullable=False)
    state_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    encrypted_attempt: Mapped[str] = mapped_column(Text, nullable=False)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
