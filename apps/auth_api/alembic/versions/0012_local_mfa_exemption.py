"""Add a closed-by-default MFA exemption for controlled local fixtures.

Revision ID: 0012_local_mfa_exemption
Revises: 0011_user_public_slug
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0012_local_mfa_exemption"
down_revision: str | None = "0011_user_public_slug"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mfa_exempt", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_exempt")
