"""Link separately billed business branches to their root workspace."""
import sqlalchemy as sa
from alembic import op

revision = "0039_business_branches"
down_revision = "0038_member_signing_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("parent_workspace_id", sa.Uuid()))
    op.create_foreign_key("fk_tenants_parent_workspace", "tenants", "tenants", ["parent_workspace_id"], ["id"])
    op.create_index("ix_tenants_parent_workspace_id", "tenants", ["parent_workspace_id"])
    op.add_column("business_upgrade_reviews", sa.Column("is_branch", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.drop_constraint("uq_business_upgrade_review_tenant", "business_upgrade_reviews", type_="unique")
    op.create_index("uq_business_upgrade_review_tenant", "business_upgrade_reviews", ["tenant_id"], unique=True, postgresql_where=sa.text("NOT is_branch"))
    op.create_index("uq_branch_review_cnpj", "business_upgrade_reviews", ["tenant_id", "cnpj_lookup"], unique=True, postgresql_where=sa.text("is_branch"))


def downgrade() -> None:
    op.drop_index("uq_branch_review_cnpj", table_name="business_upgrade_reviews")
    op.drop_index("uq_business_upgrade_review_tenant", table_name="business_upgrade_reviews")
    op.create_unique_constraint("uq_business_upgrade_review_tenant", "business_upgrade_reviews", ["tenant_id"])
    op.drop_column("business_upgrade_reviews", "is_branch")
    op.drop_index("ix_tenants_parent_workspace_id", table_name="tenants")
    op.drop_constraint("fk_tenants_parent_workspace", "tenants", type_="foreignkey")
    op.drop_column("tenants", "parent_workspace_id")
