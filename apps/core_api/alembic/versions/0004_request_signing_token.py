"""Add opaque request-level signing links."""

from alembic import op
import sqlalchemy as sa

revision = "0004_request_signing_token"
down_revision = "0003_signer_link_revocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signature_requests", sa.Column("signing_token_hash", sa.String(64), nullable=True))
    op.create_index("ix_signature_requests_signing_token_hash", "signature_requests", ["signing_token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_signature_requests_signing_token_hash", table_name="signature_requests")
    op.drop_column("signature_requests", "signing_token_hash")
