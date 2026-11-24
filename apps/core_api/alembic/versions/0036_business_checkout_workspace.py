"""Link approved reviews to separately billed business workspaces."""
from alembic import op
import sqlalchemy as sa

revision = "0036_business_checkout_workspace"
down_revision = "0035_business_upgrade_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("business_upgrade_reviews", sa.Column("business_tenant_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_business_review_destination", "business_upgrade_reviews", "tenants", ["business_tenant_id"], ["id"]
    )
    op.create_unique_constraint(
        "uq_business_review_destination", "business_upgrade_reviews", ["business_tenant_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_business_review_destination", "business_upgrade_reviews", type_="unique")
    op.drop_constraint("fk_business_review_destination", "business_upgrade_reviews", type_="foreignkey")
    op.drop_column("business_upgrade_reviews", "business_tenant_id")
