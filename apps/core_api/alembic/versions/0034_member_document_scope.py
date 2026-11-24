"""Add per-membership document visibility.

Revision ID: 0034_member_document_scope
Revises: 0033_seat_roster_timestamps
"""

import sqlalchemy as sa
from alembic import op


revision = "0034_member_document_scope"
down_revision = "0033_seat_roster_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_members",
        sa.Column("document_scope", sa.String(length=16), server_default="legacy", nullable=False),
    )
    op.alter_column("tenant_members", "document_scope", server_default="own")
    op.create_check_constraint(
        "ck_tenant_member_document_scope",
        "tenant_members",
        "document_scope IN ('legacy', 'own', 'all', 'since_joined')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tenant_member_document_scope", "tenant_members", type_="check")
    op.drop_column("tenant_members", "document_scope")
