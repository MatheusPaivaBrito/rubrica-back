"""Enterprise request preparation, signer sessions and encrypted provider configs."""
from alembic import op
import sqlalchemy as sa

revision = "0035_enterprise_workflows"
down_revision = "0034_enterprise_documents"
branch_labels = None
depends_on = None


def common_columns():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    ]


def upgrade():
    op.create_table("enterprise_providers", *common_columns(),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("sandbox", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("encrypted_configuration", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.UniqueConstraint("tenant_id", "provider", "sandbox", name="uq_enterprise_provider"))
    op.create_table("enterprise_requests", *common_columns(),
        sa.Column("compartment_id", sa.Uuid(), sa.ForeignKey("enterprise_compartments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("enterprise_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("signers", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token_public_id", sa.String(32), nullable=False),
        sa.UniqueConstraint("compartment_id", "idempotency_key", name="uq_enterprise_request_idempotency"))
    op.create_table("enterprise_signing_sessions", *common_columns(),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("enterprise_requests.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("signer_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("request_id", "signer_id", name="uq_enterprise_signer_session"))
    op.create_table("enterprise_signatures", *common_columns(),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("enterprise_requests.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("signer_id", sa.Uuid(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_hmac", sa.String(64), nullable=False),
        sa.Column("artifact_storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_size", sa.BigInteger(), nullable=False),
        sa.Column("provider_evidence", sa.JSON()),
        sa.UniqueConstraint("request_id", "signer_id", name="uq_enterprise_signature_signer"))
    op.create_table("enterprise_authorizations", *common_columns(),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("enterprise_signing_sessions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("state_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("encrypted_attempt", sa.Text(), nullable=False),
        sa.Column("sandbox", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)))
    for table in ("enterprise_providers", "enterprise_requests", "enterprise_signing_sessions", "enterprise_signatures", "enterprise_authorizations"):
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])
    op.create_index("ix_enterprise_requests_compartment_id", "enterprise_requests", ["compartment_id"])


def downgrade():
    op.drop_table("enterprise_authorizations")
    op.drop_table("enterprise_signatures")
    op.drop_table("enterprise_signing_sessions")
    op.drop_table("enterprise_requests")
    op.drop_table("enterprise_providers")
