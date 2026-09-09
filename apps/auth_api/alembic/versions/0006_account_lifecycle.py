"""Add public account lifecycle and protected international identity.

Revision ID: 0006_account_lifecycle
Revises: 0005_user_locale
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_account_lifecycle"
down_revision: str | None = "0005_user_locale"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column("users", sa.Column("identity_document_type", sa.String(length=32)))
    op.add_column("users", sa.Column("identity_document_country", sa.String(length=2)))
    op.add_column("users", sa.Column("identity_document_hash", sa.String(length=255)))
    op.add_column("users", sa.Column("identity_document_last4", sa.String(length=4)))
    op.create_table(
        "account_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_account_tokens_user_id", "account_tokens", ["user_id"])
    op.create_index("ix_account_tokens_purpose", "account_tokens", ["purpose"])
    op.create_index("ix_account_tokens_token_hash", "account_tokens", ["token_hash"], unique=True)
    op.create_index("ix_account_tokens_expires_at", "account_tokens", ["expires_at"])
    op.create_index("ix_account_tokens_deleted_at", "account_tokens", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_account_tokens_deleted_at", table_name="account_tokens")
    op.drop_index("ix_account_tokens_expires_at", table_name="account_tokens")
    op.drop_index("ix_account_tokens_token_hash", table_name="account_tokens")
    op.drop_index("ix_account_tokens_purpose", table_name="account_tokens")
    op.drop_index("ix_account_tokens_user_id", table_name="account_tokens")
    op.drop_table("account_tokens")
    op.drop_column("users", "identity_document_last4")
    op.drop_column("users", "identity_document_hash")
    op.drop_column("users", "identity_document_country")
    op.drop_column("users", "identity_document_type")
    op.drop_column("users", "email_verified")
