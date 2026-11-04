"""Enterprise contract lifecycle, purge intents and signed webhook outbox."""
from alembic import op
import sqlalchemy as sa

revision = "0039_enterprise_lifecycle"
down_revision = "0038_enterprise_copy_removal"
branch_labels = None
depends_on = None


def base():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True))]


def upgrade():
    op.create_table("enterprise_lifecycle", *base(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False),
        *[sa.Column(name, sa.DateTime(timezone=True)) for name in (
            "suspended_at", "recovery_until", "failure_cutoff", "purge_started_at", "purged_at")],
        sa.Column("revision", sa.Integer(), nullable=False))
    op.create_table("enterprise_notices", *base(), sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False), sa.Column("reference", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("delivered_to", sa.JSON(), nullable=False),
        sa.Column("email_complete", sa.Boolean(), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "kind", "reference", name="uq_enterprise_notice"))
    op.create_table("enterprise_purge_copies", *base(), sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), sa.ForeignKey("enterprise_integrations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False), sa.Column("sandbox", sa.Boolean(), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False), sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False), sa.Column("namespace", sa.String(24), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False), sa.Column("counted", sa.Boolean(), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.UniqueConstraint("source_kind", "source_id", "storage_key", name="uq_enterprise_purge_copy"))
    op.create_index("ix_enterprise_purge_copies_tenant_id", "enterprise_purge_copies", ["tenant_id"])
    op.create_table("enterprise_webhooks", *base(),
        sa.Column("integration_id", sa.Uuid(), sa.ForeignKey("enterprise_integrations.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("url", sa.String(2048), nullable=False), sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("secret_version", sa.Integer(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False))
    op.create_table("enterprise_webhook_deliveries", *base(),
        sa.Column("endpoint_id", sa.Uuid(), sa.ForeignKey("enterprise_webhooks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_until", sa.DateTime(timezone=True), nullable=False), sa.Column("error_code", sa.String(80)),
        sa.UniqueConstraint("endpoint_id", "event_id", name="uq_enterprise_webhook_event"))
    for table in ("enterprise_lifecycle", "enterprise_notices", "enterprise_purge_copies", "enterprise_webhooks", "enterprise_webhook_deliveries"):
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])


def downgrade():
    for table in ("enterprise_webhook_deliveries", "enterprise_webhooks", "enterprise_purge_copies", "enterprise_notices", "enterprise_lifecycle"):
        op.drop_table(table)
