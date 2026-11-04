"""Enterprise destinations and resumable verified migrations; no object deletion."""
from alembic import op
import sqlalchemy as sa

revision = "0037_enterprise_storage"
down_revision = "0036_enterprise_usage"
branch_labels = None
depends_on = None


def base():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True))]


def upgrade():
    for table in ("enterprise_documents", "enterprise_signatures"):
        op.add_column(table, sa.Column("rubrica_copy_deleted_at", sa.DateTime(timezone=True)))
    op.create_table("enterprise_storage_destinations", *base(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False), sa.Column("sandbox", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("encrypted_configuration", sa.Text()), sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False))
    op.create_table("enterprise_storage_policies", *base(),
        sa.Column("integration_id", sa.Uuid(), sa.ForeignKey("enterprise_integrations.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("destination_id", sa.Uuid(), sa.ForeignKey("enterprise_storage_destinations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False))
    op.create_table("enterprise_storage_migrations", *base(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), sa.ForeignKey("enterprise_integrations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("destination_id", sa.Uuid(), sa.ForeignKey("enterprise_storage_destinations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("export_acknowledged_at", sa.DateTime(timezone=True)))
    op.create_table("enterprise_migration_documents", *base(),
        sa.Column("migration_id", sa.Uuid(), sa.ForeignKey("enterprise_storage_migrations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("enterprise_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.UniqueConstraint("migration_id", "document_id", name="uq_enterprise_migration_document"))
    op.create_table("enterprise_migration_items", *base(),
        sa.Column("migration_id", sa.Uuid(), sa.ForeignKey("enterprise_storage_migrations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False), sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False), sa.Column("target_key", sa.String(512)),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("error_code", sa.String(80)),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("downloaded_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("migration_id", "source_kind", "source_id", name="uq_enterprise_migration_source"))
    for table in ("enterprise_storage_destinations", "enterprise_storage_policies", "enterprise_storage_migrations", "enterprise_migration_documents", "enterprise_migration_items"):
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])
    op.create_index("ix_enterprise_storage_destinations_tenant_id", "enterprise_storage_destinations", ["tenant_id"])
    op.create_index("ix_enterprise_storage_migrations_integration_id", "enterprise_storage_migrations", ["integration_id"])
    op.create_index("ix_enterprise_migration_items_migration_id", "enterprise_migration_items", ["migration_id"])


def downgrade():
    for table in ("enterprise_migration_items", "enterprise_migration_documents", "enterprise_storage_migrations", "enterprise_storage_policies", "enterprise_storage_destinations"):
        op.drop_table(table)
    for table in ("enterprise_documents", "enterprise_signatures"):
        op.drop_column(table, "rubrica_copy_deleted_at")
