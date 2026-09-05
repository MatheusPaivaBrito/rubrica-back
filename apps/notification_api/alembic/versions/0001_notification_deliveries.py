from alembic import op
import sqlalchemy as sa


revision = "0001_notification_deliveries"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_delivery_attempts",
        sa.Column("delivery_id", sa.String(length=80), primary_key=True),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("delivery_policy", sa.String(length=40), nullable=False),
        sa.Column("payload_stored", sa.Boolean(), nullable=False),
        sa.Column("record", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel", "idempotency_key", name="uq_notification_delivery_idempotency"),
    )
    op.create_index(
        "ix_notification_delivery_attempts_status",
        "notification_delivery_attempts",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_delivery_attempts_status",
        table_name="notification_delivery_attempts",
    )
    op.drop_table("notification_delivery_attempts")
