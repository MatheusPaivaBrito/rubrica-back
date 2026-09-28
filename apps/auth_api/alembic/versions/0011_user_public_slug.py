"""Add opaque public account slugs.

Revision ID: 0011_user_public_slug
Revises: 0010_identifier_protection
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0011_user_public_slug"
down_revision: str | None = "0010_identifier_protection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("public_slug", sa.String(32), nullable=True))
    op.execute(sa.text("UPDATE users SET public_slug = replace(gen_random_uuid()::text, '-', '')"))
    op.alter_column("users", "public_slug", nullable=False)
    op.create_index("ix_users_public_slug", "users", ["public_slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_public_slug", table_name="users")
    op.drop_column("users", "public_slug")
