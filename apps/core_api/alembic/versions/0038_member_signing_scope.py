"""Allow workspace admins to require company representation for a member."""
from alembic import op
import sqlalchemy as sa

revision = "0038_member_signing_scope"
down_revision = "0037_member_readmission_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_members", sa.Column(
        "sign_company_only", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))


def downgrade() -> None:
    op.drop_column("tenant_members", "sign_company_only")
