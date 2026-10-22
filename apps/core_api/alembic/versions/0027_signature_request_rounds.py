"""Add immutable signature request reopening rounds.

Revision ID: 0027_signature_request_rounds
Revises: 0026_stamp_configuration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0027_signature_request_rounds"
down_revision: str | None = "0026_stamp_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("signature_requests", sa.Column("parent_request_id", sa.Uuid(), nullable=True))
    op.add_column("signature_requests", sa.Column("round_number", sa.Integer(), server_default="1", nullable=False))
    op.add_column("signature_requests", sa.Column("reopened_reason", sa.String(length=500), nullable=True))
    op.add_column("signature_requests", sa.Column("reopened_by", sa.String(length=255), nullable=True))
    op.add_column("signature_requests", sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("signature_requests", sa.Column("base_artifact_storage_key", sa.String(length=255), nullable=True))
    op.add_column("signature_requests", sa.Column("base_artifact_sha256", sa.String(length=64), nullable=True))
    op.add_column("signature_requests", sa.Column("preserved_signature_count", sa.Integer(), server_default="0", nullable=False))
    op.create_foreign_key("fk_signature_requests_parent", "signature_requests", "signature_requests", ["parent_request_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_signature_requests_parent", "signature_requests", ["parent_request_id"])
    op.create_index("ix_signature_requests_parent_request_id", "signature_requests", ["parent_request_id"])
    op.create_index("ix_signature_requests_reopened_by", "signature_requests", ["reopened_by"])
    op.create_index("ix_signature_requests_reopened_at", "signature_requests", ["reopened_at"])
    op.create_index("ix_signature_requests_base_artifact_sha256", "signature_requests", ["base_artifact_sha256"])


def downgrade() -> None:
    op.drop_index("ix_signature_requests_base_artifact_sha256", table_name="signature_requests")
    op.drop_index("ix_signature_requests_reopened_at", table_name="signature_requests")
    op.drop_index("ix_signature_requests_reopened_by", table_name="signature_requests")
    op.drop_index("ix_signature_requests_parent_request_id", table_name="signature_requests")
    op.drop_constraint("uq_signature_requests_parent", "signature_requests", type_="unique")
    op.drop_constraint("fk_signature_requests_parent", "signature_requests", type_="foreignkey")
    for column in ("preserved_signature_count", "base_artifact_sha256", "base_artifact_storage_key", "reopened_at", "reopened_by", "reopened_reason", "round_number", "parent_request_id"):
        op.drop_column("signature_requests", column)
