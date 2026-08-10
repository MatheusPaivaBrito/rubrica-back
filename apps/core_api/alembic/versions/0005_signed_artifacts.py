"""Add recoverable request links and signed PDF artifacts."""

from alembic import op
import sqlalchemy as sa

revision = "0005_signed_artifacts"
down_revision = "0004_request_signing_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("signature_requests", sa.Column("signing_token_nonce", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_signature_requests_signing_token_nonce", "signature_requests", ["signing_token_nonce"])
    op.add_column("signatures", sa.Column("evidence_sha256", sa.String(64), nullable=True))
    op.add_column("signatures", sa.Column("artifact_storage_key", sa.String(255), nullable=True))
    op.add_column("signatures", sa.Column("artifact_sha256", sa.String(64), nullable=True))
    op.create_index("ix_signatures_evidence_sha256", "signatures", ["evidence_sha256"])
    op.create_index("ix_signatures_artifact_sha256", "signatures", ["artifact_sha256"])
    op.create_unique_constraint("uq_signatures_artifact_storage_key", "signatures", ["artifact_storage_key"])


def downgrade() -> None:
    op.drop_constraint("uq_signatures_artifact_storage_key", "signatures", type_="unique")
    op.drop_index("ix_signatures_artifact_sha256", table_name="signatures")
    op.drop_index("ix_signatures_evidence_sha256", table_name="signatures")
    op.drop_column("signatures", "artifact_sha256")
    op.drop_column("signatures", "artifact_storage_key")
    op.drop_column("signatures", "evidence_sha256")
    op.drop_constraint("uq_signature_requests_signing_token_nonce", "signature_requests", type_="unique")
    op.drop_column("signature_requests", "signing_token_nonce")
