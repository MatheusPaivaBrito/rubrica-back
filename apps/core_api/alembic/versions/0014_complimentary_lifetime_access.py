"""Add staff-managed complimentary lifetime access.

Revision ID: 0014_complimentary_access
Revises: 0013_euro_tenant_currency
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0014_complimentary_access"
down_revision: str | None = "0013_euro_tenant_currency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_accounts",
        sa.Column(
            "complimentary_lifetime",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "billing_accounts",
        sa.Column("complimentary_granted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "billing_accounts",
        sa.Column("complimentary_granted_by", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "billing_accounts",
        sa.Column("complimentary_grant_reason", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("billing_accounts", "complimentary_grant_reason")
    op.drop_column("billing_accounts", "complimentary_granted_by")
    op.drop_column("billing_accounts", "complimentary_granted_at")
    op.drop_column("billing_accounts", "complimentary_lifetime")
