"""Store the preferred language for signature invitations.

Revision ID: 0017_signer_preferred_locale
Revises: 0016_subscription_cancellation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0017_signer_preferred_locale"
down_revision: str | None = "0016_subscription_cancellation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "signers",
        sa.Column(
            "preferred_locale",
            sa.String(length=10),
            server_default="en",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("signers", "preferred_locale")
