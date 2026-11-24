"""Set the database timestamp defaults expected by seat roster inserts.

Revision ID: 0033_seat_roster_timestamps
Revises: 0032_pending_billing_changes
"""

from alembic import op
import sqlalchemy as sa


revision = "0033_seat_roster_timestamps"
down_revision = "0032_pending_billing_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tenant_seat_rosters", "created_at", server_default=sa.func.now())
    op.alter_column("tenant_seat_rosters", "updated_at", server_default=sa.func.now())


def downgrade() -> None:
    op.alter_column("tenant_seat_rosters", "updated_at", server_default=None)
    op.alter_column("tenant_seat_rosters", "created_at", server_default=None)
