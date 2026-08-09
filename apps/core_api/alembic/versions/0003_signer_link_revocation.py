"""Add individual signing-link revocation."""

from alembic import op
import sqlalchemy as sa

revision = "0003_signer_link_revocation"
down_revision = "0002_signature_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signers", sa.Column("link_revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_signers_link_revoked_at", "signers", ["link_revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_signers_link_revoked_at", table_name="signers")
    op.drop_column("signers", "link_revoked_at")
