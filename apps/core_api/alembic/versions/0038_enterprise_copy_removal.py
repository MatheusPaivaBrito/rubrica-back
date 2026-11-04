"""Durable source-copy removal intents; no document/object mutation."""
from alembic import op
import sqlalchemy as sa

revision = "0038_enterprise_copy_removal"
down_revision = "0037_enterprise_storage"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("enterprise_copy_removals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("migration_item_id", sa.Uuid(), sa.ForeignKey("enterprise_migration_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("enterprise_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False), sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(80)), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_kind", "source_id", "storage_key", name="uq_enterprise_removal_copy"))
    for column in ("deleted_at", "document_id", "status"):
        op.create_index(f"ix_enterprise_copy_removals_{column}", "enterprise_copy_removals", [column])


def downgrade():
    op.drop_table("enterprise_copy_removals")
