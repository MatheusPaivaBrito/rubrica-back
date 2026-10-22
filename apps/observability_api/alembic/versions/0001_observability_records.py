from alembic import op
import sqlalchemy as sa


revision = "0001_observability_records"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "observability_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_observability_records_record_type_created_at",
        "observability_records",
        ["record_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_observability_records_record_type_created_at",
        table_name="observability_records",
    )
    op.drop_table("observability_records")
