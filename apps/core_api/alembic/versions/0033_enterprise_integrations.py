"""Persist Core-owned integrations and compartments; credentials belong to Auth."""

from alembic import op
import sqlalchemy as sa

revision = "0033_enterprise_integrations"
down_revision = "0032_pending_billing_changes"
branch_labels = None
depends_on = None


def common_columns():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    ]


def upgrade():
    op.create_table(
        "enterprise_integrations", *common_columns(),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("environment", sa.String(24), nullable=False),
        sa.Column("sandbox", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
    )
    op.create_table(
        "enterprise_compartments", *common_columns(),
        sa.Column("integration_id", sa.Uuid(), sa.ForeignKey("enterprise_integrations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
    )
    for table, column in (("enterprise_integrations", "tenant_id"),
                          ("enterprise_compartments", "integration_id")):
        op.create_index(f"ix_{table}_{column}", table, [column])
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])


def downgrade():
    op.drop_table("enterprise_compartments")
    op.drop_table("enterprise_integrations")
