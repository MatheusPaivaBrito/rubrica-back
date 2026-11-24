"""Record the start of a new admission for filtering the member's own files."""
from alembic import op
import sqlalchemy as sa

revision = "0037_member_readmission_scope"
down_revision = "0036_business_checkout_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_members", sa.Column("own_files_since", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("tenant_members", "own_files_since")
