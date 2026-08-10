"""Add user name and protected CPF."""

from alembic import op
import sqlalchemy as sa

revision = "0003_user_identity"
down_revision = "0002_access_control_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(length=180), nullable=True))
    op.add_column("users", sa.Column("cpf_hash", sa.String(length=255), nullable=True))
    op.create_index("ix_users_name", "users", ["name"])


def downgrade() -> None:
    op.drop_index("ix_users_name", table_name="users")
    op.drop_column("users", "cpf_hash")
    op.drop_column("users", "name")
