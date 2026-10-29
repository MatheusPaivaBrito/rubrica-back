"""Store the nominal seat roster selected for a future billing cycle.

Revision ID: 0031_tenant_seat_rosters
Revises: 0030_billing_contracted_seats
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_tenant_seat_rosters"
down_revision = "0030_billing_contracted_seats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_seat_rosters",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("cycle_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seat_limit", sa.Integer(), nullable=False),
        sa.Column("member_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="scheduled", nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "cycle_starts_at", name="uq_tenant_seat_roster_cycle"),
    )
    op.create_index(
        op.f("ix_tenant_seat_rosters_tenant_id"),
        "tenant_seat_rosters",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tenant_seat_rosters_cycle_starts_at"),
        "tenant_seat_rosters",
        ["cycle_starts_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tenant_seat_rosters_cycle_starts_at"),
        table_name="tenant_seat_rosters",
    )
    op.drop_index(
        op.f("ix_tenant_seat_rosters_tenant_id"),
        table_name="tenant_seat_rosters",
    )
    op.drop_table("tenant_seat_rosters")
