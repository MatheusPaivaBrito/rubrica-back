"""Add the tenant payment ledger.

Revision ID: 0012_billing_payments
Revises: 0011_billing_webhook_ordering
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0012_billing_payments"
down_revision: str | None = "0011_billing_webhook_ordering"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_payments",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=160), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=160), nullable=True),
        sa.Column("provider_event_id", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount_due_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("amount_paid_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_payment_id", name="uq_billing_payment_provider_id"),
    )
    op.create_index("ix_billing_payments_tenant_id", "billing_payments", ["tenant_id"])
    op.create_index("ix_billing_payments_status", "billing_payments", ["status"])
    op.create_index("ix_billing_payments_deleted_at", "billing_payments", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_billing_payments_deleted_at", table_name="billing_payments")
    op.drop_index("ix_billing_payments_status", table_name="billing_payments")
    op.drop_index("ix_billing_payments_tenant_id", table_name="billing_payments")
    op.drop_table("billing_payments")
