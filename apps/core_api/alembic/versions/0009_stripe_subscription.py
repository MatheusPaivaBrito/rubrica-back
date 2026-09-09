"""Add Stripe subscription identity to billing accounts.

Revision ID: 0009_stripe_subscription
Revises: 0008_tenant_localization
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0009_stripe_subscription"
down_revision: str | None = "0008_tenant_localization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_accounts",
        sa.Column("provider_subscription_id", sa.String(length=160)),
    )
    op.create_unique_constraint(
        "uq_billing_accounts_provider_subscription_id",
        "billing_accounts",
        ["provider_subscription_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_billing_accounts_provider_subscription_id",
        "billing_accounts",
        type_="unique",
    )
    op.drop_column("billing_accounts", "provider_subscription_id")
