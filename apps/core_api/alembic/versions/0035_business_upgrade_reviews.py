"""Store manual CNPJ review requests."""
import sqlalchemy as sa
from alembic import op

revision = "0035_business_upgrade_reviews"
down_revision = "0034_member_document_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_upgrade_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("legal_name", sa.String(240), nullable=False),
        sa.Column("cnpj_encrypted", sa.String(512), nullable=False),
        sa.Column("cnpj_lookup", sa.String(64), nullable=False),
        sa.Column("cnpj_masked", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reviewed_by", sa.String(255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", name="uq_business_upgrade_review_tenant"),
    )
    op.create_index(
        "uq_business_upgrade_review_approved_cnpj",
        "business_upgrade_reviews", ["cnpj_lookup"], unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    )


def downgrade() -> None:
    op.drop_table("business_upgrade_reviews")
