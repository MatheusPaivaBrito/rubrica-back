"""Durable provider checkpoints and bounded distributed worker jobs."""
from alembic import op
import sqlalchemy as sa

revision = "0041_enterprise_execution"
down_revision = "0040_enterprise_closure"
branch_labels = depends_on = None


def base():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True))]


def upgrade():
    op.create_table("enterprise_administration_budgets", *base(),
        sa.Column("identity", sa.String(64), nullable=False, unique=True),
        sa.Column("minute", sa.Integer(), nullable=False), sa.Column("count", sa.Integer(), nullable=False))
    op.create_table("enterprise_operations", *base(),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("enterprise_requests.id", ondelete="RESTRICT"), nullable=False),
        *[sa.Column(name, sa.Uuid(), nullable=False) for name in ("signer_id", "tenant_id", "signature_id", "owner")],
        sa.Column("status", sa.String(24), nullable=False), sa.Column("command_sha256", sa.String(64), nullable=False),
        sa.Column("encrypted_checkpoint", sa.Text()), sa.Column("error_code", sa.String(80)),
        sa.UniqueConstraint("request_id", "signer_id", name="uq_enterprise_provider_operation"))
    op.create_table("enterprise_jobs", *base(),
        *[sa.Column(name, sa.Uuid(), nullable=False) for name in ("tenant_id", "integration_id", "compartment_id")],
        sa.Column("signing_session_id", sa.Uuid()),
        sa.Column("sandbox", sa.Boolean(), nullable=False), sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("dedup_key", sa.String(64), nullable=False, unique=True), sa.Column("encrypted_payload", sa.Text()),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("result", sa.JSON()), sa.Column("error_code", sa.String(80)),
        sa.Column("owner", sa.Uuid()), sa.Column("lease_until", sa.DateTime(timezone=True)), sa.Column("attempts", sa.Integer(), nullable=False))
    op.create_table("enterprise_execution_slots", *base(), sa.Column("environment", sa.String(24), nullable=False),
        sa.Column("sandbox", sa.Boolean(), nullable=False), sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Uuid()), sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("environment", "sandbox", "number", name="uq_enterprise_execution_slot"))
    for table in ("enterprise_operations", "enterprise_jobs", "enterprise_execution_slots", "enterprise_administration_budgets"):
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])
    op.create_index("ix_enterprise_jobs_tenant_id", "enterprise_jobs", ["tenant_id"])
    op.create_index("ix_enterprise_jobs_status", "enterprise_jobs", ["status"])


def downgrade():
    for table in ("enterprise_execution_slots", "enterprise_jobs", "enterprise_operations", "enterprise_administration_budgets"):
        op.drop_table(table)
