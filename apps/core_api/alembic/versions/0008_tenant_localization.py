"""Add locale, country, timezone, and currency to tenants.

Revision ID: 0008_tenant_localization
Revises: 0007_uuid_identifiers
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_tenant_localization"
down_revision: str | None = "0007_uuid_identifiers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("default_locale", sa.String(length=10), server_default="en", nullable=False),
    )
    op.add_column("tenants", sa.Column("country_code", sa.String(length=2), nullable=True))
    op.add_column(
        "tenants",
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
    )
    op.add_column(
        "tenants",
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("tenants", "currency")
    op.drop_column("tenants", "timezone")
    op.drop_column("tenants", "country_code")
    op.drop_column("tenants", "default_locale")
