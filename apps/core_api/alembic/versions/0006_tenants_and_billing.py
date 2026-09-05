"""Add tenant boundaries and the plan-free billing foundation."""

from alembic import op
import sqlalchemy as sa


revision = "0006_tenants_billing"
down_revision = "0005_signed_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])
    op.create_index("ix_tenants_status", "tenants", ["status"])
    op.create_index("ix_tenants_deleted_at", "tenants", ["deleted_at"])
    op.create_table(
        "tenant_members",
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("auth_user_id", sa.String(255), nullable=False),
        sa.Column("role", sa.String(24), nullable=False, server_default="member"),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "auth_user_id", name="uq_tenant_member_identity"),
    )
    for column in ("tenant_id", "auth_user_id", "role", "deleted_at"):
        op.create_index(f"ix_tenant_members_{column}", "tenant_members", [column])
    op.add_column("documents", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.execute(sa.text("INSERT INTO tenants (name, slug, status) SELECT organization_id, 'legacy-' || md5(organization_id), 'active' FROM documents GROUP BY organization_id"))
    op.execute(sa.text("UPDATE documents SET tenant_id = tenants.id FROM tenants WHERE tenants.name = documents.organization_id AND tenants.slug = 'legacy-' || md5(documents.organization_id)"))
    op.execute(sa.text("INSERT INTO tenant_members (tenant_id, auth_user_id, role) SELECT DISTINCT tenant_id, lower(created_by), 'admin' FROM documents"))
    op.alter_column("documents", "tenant_id", nullable=False)
    op.create_foreign_key("fk_documents_tenant", "documents", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_table(
        "billing_accounts",
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="not_configured"),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("provider_customer_id", sa.String(160), nullable=True, unique=True),
        sa.Column("current_product_code", sa.String(80), nullable=True),
        sa.Column("current_period_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_billing_accounts_tenant_id", "billing_accounts", ["tenant_id"])
    op.create_index("ix_billing_accounts_status", "billing_accounts", ["status"])
    op.create_index("ix_billing_accounts_deleted_at", "billing_accounts", ["deleted_at"])
    op.create_table(
        "billing_events",
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(240), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(160), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_sanitized", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="received"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_billing_event_provider_id"),
    )
    for column in ("tenant_id", "event_type", "deleted_at"):
        op.create_index(f"ix_billing_events_{column}", "billing_events", [column])


def downgrade() -> None:
    op.drop_table("billing_events")
    op.drop_table("billing_accounts")
    op.drop_index("ix_documents_tenant_id", table_name="documents")
    op.drop_constraint("fk_documents_tenant", "documents", type_="foreignkey")
    op.drop_column("documents", "tenant_id")
    op.drop_table("tenant_members")
    op.drop_table("tenants")
