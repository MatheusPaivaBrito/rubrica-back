"""Add durable idempotent signature operations.

Revision ID: 0025_signature_operations
Revises: 0024_immutable_signature_records
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0025_signature_operations"
down_revision: str | None = "0024_immutable_signature_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signature_operations",
        sa.Column("signature_request_id", sa.Uuid(), nullable=False),
        sa.Column("signer_id", sa.Uuid(), nullable=False),
        sa.Column("auth_user_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("expected_signature_count", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifact_storage_key", sa.String(length=255), nullable=True),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("trusted_timestamp_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["signature_request_id"], ["signature_requests.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["signer_id"], ["signers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_storage_key"),
        sa.UniqueConstraint("signature_request_id", "signer_id"),
    )
    for column in (
        "signature_request_id",
        "signer_id",
        "auth_user_id",
        "status",
        "lease_expires_at",
        "evidence_sha256",
        "artifact_sha256",
        "error_code",
        "deleted_at",
    ):
        op.create_index(
            f"ix_signature_operations_{column}", "signature_operations", [column]
        )


def downgrade() -> None:
    op.drop_table("signature_operations")
