"""Track scheduled Stripe subscription cancellations.

Revision ID: 0016_subscription_cancellation
Revises: 0015_monthly_file_allowances
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016_subscription_cancellation"
down_revision: str | None = "0015_monthly_file_allowances"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_accounts",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "billing_accounts",
        sa.Column("cancels_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("billing_accounts", "cancels_at")
    op.drop_column("billing_accounts", "cancel_at_period_end")
