"""Record when the business workspace entered export-only mode."""
import sqlalchemy as sa
from alembic import op

revision = "0041_workspace_closed_at"
down_revision = "0040_workspace_closure_request"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("workspace_closed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("tenants", "workspace_closed_at")
