"""Record when a signature request is opened.

Revision ID: 0029_signature_request_opened_at
Revises: 0028_signer_signature_mode
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_signature_request_opened_at"
down_revision = "0028_signer_signature_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signature_requests",
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_signature_requests_opened_at"),
        "signature_requests",
        ["opened_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_signature_requests_opened_at"), table_name="signature_requests")
    op.drop_column("signature_requests", "opened_at")
