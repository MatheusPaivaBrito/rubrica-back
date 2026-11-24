"""Record requests to close a business workspace."""
import sqlalchemy as sa
from alembic import op

revision = "0040_workspace_closure_request"
down_revision = "0039_business_branches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("closure_requested_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("tenants", "closure_requested_at")
