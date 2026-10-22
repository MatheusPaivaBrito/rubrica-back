"""Add stamp placement and branding configuration.

Revision ID: 0026_stamp_configuration
Revises: 0025_signature_operations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0026_stamp_configuration"
down_revision: str | None = "0025_signature_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("stamp_customization", sa.JSON(), nullable=True))
    op.add_column("signature_requests", sa.Column("stamp_placements", sa.JSON(), nullable=True))
    op.add_column("signature_requests", sa.Column("stamp_customization_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("signature_requests", "stamp_customization_snapshot")
    op.drop_column("signature_requests", "stamp_placements")
    op.drop_column("tenants", "stamp_customization")
