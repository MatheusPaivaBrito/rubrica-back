"""Store the preferred identifier for each account."""
from alembic import op
import sqlalchemy as sa

revision = "0013_preferred_identifier"
down_revision = "0012_local_mfa_exemption"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferred_identifier_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_users_preferred_identifier", "users", "user_identifiers",
        ["preferred_identifier_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_preferred_identifier", "users", type_="foreignkey")
    op.drop_column("users", "preferred_identifier_id")
