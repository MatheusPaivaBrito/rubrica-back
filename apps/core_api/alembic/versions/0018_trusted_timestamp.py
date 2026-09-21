"""Store trusted timestamp metadata.

Revision ID: 0018_trusted_timestamp
Revises: 0017_signer_preferred_locale
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_trusted_timestamp"
down_revision: str | None = "0017_signer_preferred_locale"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("signatures", sa.Column("trusted_timestamp_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("signatures", "trusted_timestamp_json")
