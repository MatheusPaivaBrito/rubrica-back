"""Enforce stable Auth UUID membership identity.

Revision ID: 0022_stable_membership_identity
Revises: 0021_public_tenant_account_slugs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0022_stable_membership_identity"
down_revision: str | None = "0021_public_tenant_account_slugs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_tenant_member_user_uuid",
        "tenant_members",
        ["tenant_id", "auth_user_uuid"],
        unique=True,
        postgresql_where=sa.text("auth_user_uuid IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_tenant_member_user_uuid", table_name="tenant_members")
