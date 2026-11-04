"""Idempotent tenant credential retirement; Auth database only."""
from alembic import op
import sqlalchemy as sa

revision = "0014_machine_retirements"
down_revision = "0013_machine_credentials"
branch_labels = depends_on = None


def upgrade():
    op.create_table("machine_retirements", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)), sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(24), nullable=False), sa.Column("operation_id", sa.Uuid(), nullable=False, unique=True))
    op.create_index("ix_machine_retirements_deleted_at", "machine_retirements", ["deleted_at"])


def downgrade():
    op.drop_table("machine_retirements")
