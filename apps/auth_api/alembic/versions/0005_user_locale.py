"""Add the preferred locale to Auth users.

Revision ID: 0005_user_locale
Revises: 0004_uuid_identifiers
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_user_locale"
down_revision: str | None = "0004_uuid_identifiers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("preferred_locale", sa.String(length=10), server_default="en", nullable=False),
    )
    op.create_index("ix_users_preferred_locale", "users", ["preferred_locale"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_preferred_locale", table_name="users")
    op.drop_column("users", "preferred_locale")
