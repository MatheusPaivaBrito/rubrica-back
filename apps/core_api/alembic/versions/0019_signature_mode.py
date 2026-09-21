"""Choose the signature mode when opening a request.

Revision ID: 0019_signature_mode
Revises: 0018_trusted_timestamp
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_signature_mode"
down_revision: str | None = "0018_trusted_timestamp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "signature_requests",
        sa.Column("signature_mode", sa.String(length=30), server_default="evidence", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("signature_requests", "signature_mode")
