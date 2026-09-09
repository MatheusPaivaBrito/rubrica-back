"""Add MFA replay protection and security audit events.

Revision ID: 0008_mfa_hardening
Revises: 0007_mfa_totp
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_mfa_hardening"
down_revision: str | None = "0007_mfa_totp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_last_used_step", sa.Integer()))
    op.create_table(
        "mfa_security_events",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("metadata_sanitized", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mfa_security_events_user_id", "mfa_security_events", ["user_id"])
    op.create_index("ix_mfa_security_events_action", "mfa_security_events", ["action"])
    op.create_index("ix_mfa_security_events_deleted_at", "mfa_security_events", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_mfa_security_events_deleted_at", table_name="mfa_security_events")
    op.drop_index("ix_mfa_security_events_action", table_name="mfa_security_events")
    op.drop_index("ix_mfa_security_events_user_id", table_name="mfa_security_events")
    op.drop_table("mfa_security_events")
    op.drop_column("users", "mfa_last_used_step")
