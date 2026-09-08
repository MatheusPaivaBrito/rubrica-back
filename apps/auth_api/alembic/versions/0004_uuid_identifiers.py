"""Migrate Auth entity identifiers from integers to UUIDs."""

from alembic import op
import sqlalchemy as sa


revision = "0004_uuid_identifiers"
down_revision = "0003_user_identity"
branch_labels = None
depends_on = None


def _uuid(expression: str) -> str:
    return f"('00000000-0000-0000-0000-' || lpad(to_hex({expression}), 12, '0'))::uuid"


def upgrade() -> None:
    op.drop_constraint("user_roles_user_id_fkey", "user_roles", type_="foreignkey")
    op.alter_column("users", "id", server_default=None)
    op.alter_column("user_roles", "id", server_default=None)
    op.alter_column("users", "id", type_=sa.Uuid(), postgresql_using=_uuid("id"))
    op.alter_column("user_roles", "id", type_=sa.Uuid(), postgresql_using=_uuid("id"))
    op.alter_column("user_roles", "user_id", type_=sa.Uuid(), postgresql_using=_uuid("user_id"))
    op.create_foreign_key("user_roles_user_id_fkey", "user_roles", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_user_roles_deleted_at", "user_roles", ["deleted_at"])
    # ``users.email`` is represented by the existing unique index in the model.
    # Keeping both that index and the historical constraint duplicates enforcement.
    op.drop_constraint("uq_users_email", "users", type_="unique")


def downgrade() -> None:
    raise RuntimeError("UUID identifier migration is intentionally irreversible")
