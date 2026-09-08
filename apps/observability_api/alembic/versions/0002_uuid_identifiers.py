"""Migrate Observability record identifiers to UUIDs."""

from alembic import op
import sqlalchemy as sa


revision = "0002_uuid_identifiers"
down_revision = "0001_observability_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    expression = "CASE WHEN record_key ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN record_key::uuid ELSE md5(record_key)::uuid END"
    for table in ("observability_incidents", "observability_alert_events", "observability_release_markers"):
        op.alter_column(table, "record_key", type_=sa.Uuid(), postgresql_using=expression)


def downgrade() -> None:
    raise RuntimeError("UUID identifier migration is intentionally irreversible")
