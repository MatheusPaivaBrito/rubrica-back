from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from core_api.infrastructure.database.connection import BaseEntity


class StorageDestination(BaseEntity):
    __tablename__ = "enterprise_storage_destinations"
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    encrypted_configuration: Mapped[str | None] = mapped_column(Text)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)


class StoragePolicy(BaseEntity):
    __tablename__ = "enterprise_storage_policies"
    integration_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_integrations.id", ondelete="RESTRICT"), nullable=False, unique=True)
    destination_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_storage_destinations.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)


class StorageMigration(BaseEntity):
    __tablename__ = "enterprise_storage_migrations"
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    integration_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_integrations.id", ondelete="RESTRICT"), nullable=False, index=True)
    destination_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_storage_destinations.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    export_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MigrationDocument(BaseEntity):
    __tablename__ = "enterprise_migration_documents"
    __table_args__ = (UniqueConstraint("migration_id", "document_id", name="uq_enterprise_migration_document"),)
    migration_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_storage_migrations.id", ondelete="RESTRICT"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_documents.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")


class MigrationItem(BaseEntity):
    __tablename__ = "enterprise_migration_items"
    __table_args__ = (UniqueConstraint("migration_id", "source_kind", "source_id", name="uq_enterprise_migration_source"),)
    migration_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_storage_migrations.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_key: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    error_code: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CopyRemoval(BaseEntity):
    """Committed intent precedes external deletion; keys identify a copy generation."""
    __tablename__ = "enterprise_copy_removals"
    __table_args__ = (UniqueConstraint("source_kind", "source_id", "storage_key", name="uq_enterprise_removal_copy"),)
    migration_item_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_migration_items.id", ondelete="RESTRICT"), nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("enterprise_documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
