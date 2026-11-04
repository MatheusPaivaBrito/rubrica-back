"""Isolated, idempotent enterprise usage projection."""
from alembic import op
import sqlalchemy as sa

revision = "0003_enterprise_usage"
down_revision = "0002_operational_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("enterprise_usage_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        *[sa.Column(name, sa.Uuid(), nullable=False) for name in ("tenant_id", "integration_id", "compartment_id")],
        sa.Column("token_public_id", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(24), nullable=False),
        sa.Column("sandbox", sa.Boolean(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("bytes_count", sa.BigInteger(), nullable=False),
        sa.Column("billable", sa.Boolean(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("status_code", sa.Integer()), sa.Column("duration_ms", sa.Float()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False))
    op.create_index("ix_enterprise_projection_tenant_window", "enterprise_usage_records",
        ["tenant_id", "integration_id", "sandbox", "occurred_at"])


def downgrade():
    op.drop_table("enterprise_usage_records")
