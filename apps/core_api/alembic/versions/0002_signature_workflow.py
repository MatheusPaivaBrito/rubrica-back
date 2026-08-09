"""Create document and signature workflow tables."""

from alembic import op
import sqlalchemy as sa

revision = "0002_signature_workflow"
down_revision = "0001_core_base"
branch_labels = None
depends_on = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table("documents", *_base_columns(), sa.Column("organization_id", sa.String(120), nullable=False), sa.Column("title", sa.String(240), nullable=False), sa.Column("original_filename", sa.String(255), nullable=False), sa.Column("content_type", sa.String(160), nullable=False), sa.Column("storage_key", sa.String(255), nullable=False, unique=True), sa.Column("sha256", sa.String(64), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("created_by", sa.String(255), nullable=False))
    op.create_table("document_versions", *_base_columns(), sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("original_filename", sa.String(255), nullable=False), sa.Column("content_type", sa.String(160), nullable=False), sa.Column("storage_key", sa.String(255), nullable=False, unique=True), sa.Column("sha256", sa.String(64), nullable=False), sa.Column("size_bytes", sa.BigInteger(), nullable=False), sa.Column("created_by", sa.String(255), nullable=False), sa.UniqueConstraint("document_id", "version"))
    op.create_table("signature_requests", *_base_columns(), sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False), sa.Column("document_version", sa.Integer(), nullable=False), sa.Column("document_sha256", sa.String(64), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_by", sa.String(255), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_table("signers", *_base_columns(), sa.Column("signature_request_id", sa.Integer(), sa.ForeignKey("signature_requests.id", ondelete="RESTRICT"), nullable=False), sa.Column("auth_user_id", sa.String(255), nullable=False), sa.Column("name", sa.String(180), nullable=False), sa.Column("email", sa.String(254), nullable=False), sa.Column("signing_token_hash", sa.String(64), nullable=False, unique=True), sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("signed_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("signature_request_id", "auth_user_id"))
    op.create_table("signatures", *_base_columns(), sa.Column("signature_request_id", sa.Integer(), sa.ForeignKey("signature_requests.id", ondelete="RESTRICT"), nullable=False), sa.Column("signer_id", sa.Integer(), sa.ForeignKey("signers.id", ondelete="RESTRICT"), nullable=False), sa.Column("auth_user_id", sa.String(255), nullable=False), sa.Column("document_sha256", sa.String(64), nullable=False), sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("evidence_json", sa.JSON(), nullable=False), sa.UniqueConstraint("signature_request_id", "signer_id"), sa.UniqueConstraint("signature_request_id", "auth_user_id"))
    op.create_table("audit_events", *_base_columns(), sa.Column("signature_request_id", sa.Integer(), sa.ForeignKey("signature_requests.id", ondelete="RESTRICT")), sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False), sa.Column("actor_type", sa.String(30), nullable=False), sa.Column("actor_id", sa.String(255), nullable=False), sa.Column("action", sa.String(100), nullable=False), sa.Column("entity_type", sa.String(60), nullable=False), sa.Column("entity_id", sa.String(255), nullable=False), sa.Column("correlation_id", sa.String(64), nullable=False), sa.Column("metadata_sanitized", sa.JSON(), nullable=False))


def downgrade() -> None:
    for table in ("audit_events", "signatures", "signers", "signature_requests", "document_versions", "documents"):
        op.drop_table(table)
