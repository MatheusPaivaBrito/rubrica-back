"""Add Stripe webhook ordering and payment grace period.

Revision ID: 0011_billing_webhook_ordering
Revises: 0010_signature_entitlements
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0011_billing_webhook_ordering"
down_revision: str | None = "0010_signature_entitlements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("billing_accounts", sa.Column("grace_period_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("billing_accounts", sa.Column("last_provider_event_created_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("billing_accounts", "last_provider_event_created_at")
    op.drop_column("billing_accounts", "grace_period_ends_at")
