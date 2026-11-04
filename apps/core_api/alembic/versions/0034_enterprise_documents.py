"""Isolated enterprise upload intake with idempotency and quarantine."""
from alembic import op
import sqlalchemy as sa

revision = "0034_enterprise_documents"
down_revision = "0033_enterprise_integrations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("enterprise_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("compartment_id", sa.Uuid(), sa.ForeignKey("enterprise_compartments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("filename", sa.String(120), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("token_public_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.UniqueConstraint("compartment_id", "idempotency_key", name="uq_enterprise_upload_idempotency"))
    for column in ("compartment_id", "deleted_at"):
        op.create_index(f"ix_enterprise_documents_{column}", "enterprise_documents", [column])


def downgrade():
    op.drop_table("enterprise_documents")
