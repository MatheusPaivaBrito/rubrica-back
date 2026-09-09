"""Add TOTP MFA and one-time recovery codes.

Revision ID: 0007_mfa_totp
Revises: 0006_account_lifecycle
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007_mfa_totp"
down_revision: str | None = "0006_account_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("users", sa.Column("mfa_secret_ciphertext", sa.String(length=512)))
    op.add_column("users", sa.Column("mfa_pending_secret_ciphertext", sa.String(length=512)))
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])
    op.create_index("ix_mfa_recovery_codes_deleted_at", "mfa_recovery_codes", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_mfa_recovery_codes_deleted_at", table_name="mfa_recovery_codes")
    op.drop_index("ix_mfa_recovery_codes_user_id", table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_column("users", "mfa_pending_secret_ciphertext")
    op.drop_column("users", "mfa_secret_ciphertext")
    op.drop_column("users", "mfa_enabled")
