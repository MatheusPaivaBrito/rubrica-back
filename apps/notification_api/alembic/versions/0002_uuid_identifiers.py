"""Migrate Notification delivery identifiers to UUIDs."""

from alembic import op
import sqlalchemy as sa


revision = "0002_uuid_identifiers"
down_revision = "0001_notification_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    expression = "CASE WHEN delivery_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN delivery_id::uuid ELSE md5(delivery_id)::uuid END"
    op.alter_column("notification_delivery_attempts", "delivery_id", type_=sa.Uuid(), postgresql_using=expression)


def downgrade() -> None:
    raise RuntimeError("UUID identifier migration is intentionally irreversible")
