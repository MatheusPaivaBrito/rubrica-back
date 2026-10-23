"""Choose the signature provider per signer.

Revision ID: 0028_signer_signature_mode
Revises: 0027_signature_request_rounds
"""

from alembic import op
import sqlalchemy as sa

revision = "0028_signer_signature_mode"
down_revision = "0027_signature_request_rounds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signers", sa.Column("signature_mode", sa.String(length=30), nullable=False, server_default="serpro_timestamp"))


def downgrade() -> None:
    op.drop_column("signers", "signature_mode")
