"""Rotate opaque public slugs for tenant routes.

Revision ID: 0021_public_tenant_account_slugs
Revises: 0020_business_tenants
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0021_public_tenant_account_slugs"
down_revision: str | None = "0020_business_tenants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing slugs could contain names or hashes derived from e-mail. Replace
    # every public tenant locator while preserving the stable internal UUID.
    op.execute(sa.text("UPDATE tenants SET slug = replace(gen_random_uuid()::text, '-', '')"))


def downgrade() -> None:
    pass
