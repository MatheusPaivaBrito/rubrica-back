"""Track the Stripe source of business tenant identity.

Revision ID: 0023_stripe_business_identity
Revises: 0022_stable_membership_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0023_stripe_business_identity"
down_revision: str | None = "0022_stable_membership_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("registration_source", sa.String(32), nullable=True))
    op.add_column(
        "tenants",
        sa.Column("registration_provider_reference", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "registration_provider_reference")
    op.drop_column("tenants", "registration_source")
