"""Keep plan capacity unchanged until the related Stripe payment succeeds.

Revision ID: 0032_pending_billing_changes
Revises: 0031_tenant_seat_rosters
"""

from alembic import op
import sqlalchemy as sa


revision = "0032_pending_billing_changes"
down_revision = "0031_tenant_seat_rosters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_accounts", sa.Column("pending_product_code", sa.String(length=80)))
    op.add_column("billing_accounts", sa.Column("pending_contracted_seats", sa.Integer()))
    op.add_column("billing_accounts", sa.Column("pending_change_kind", sa.String(length=24)))
    op.add_column("billing_accounts", sa.Column("pending_change_effective_at", sa.DateTime(timezone=True)))
    op.add_column("billing_accounts", sa.Column("pending_provider_invoice_id", sa.String(length=160)))


def downgrade() -> None:
    op.drop_column("billing_accounts", "pending_provider_invoice_id")
    op.drop_column("billing_accounts", "pending_change_effective_at")
    op.drop_column("billing_accounts", "pending_change_kind")
    op.drop_column("billing_accounts", "pending_contracted_seats")
    op.drop_column("billing_accounts", "pending_product_code")
