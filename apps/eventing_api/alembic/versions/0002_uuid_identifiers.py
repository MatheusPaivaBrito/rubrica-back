"""Migrate Eventing identifiers to UUIDs."""

from alembic import op
import sqlalchemy as sa


revision = "0002_uuid_identifiers"
down_revision = "0001_eventing_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    legacy_uuid = "('00000000-0000-0000-0000-' || lpad(to_hex(id), 12, '0'))::uuid"
    op.alter_column("event_outbox", "id", server_default=None)
    op.alter_column("event_outbox", "id", type_=sa.Uuid(), postgresql_using=legacy_uuid)
    op.alter_column("event_outbox", "event_id", type_=sa.Uuid(), postgresql_using="event_id::uuid")
    for column in ("available_at", "deleted_at", "occurred_at", "source"):
        op.create_index(f"ix_event_outbox_{column}", "event_outbox", [column])


def downgrade() -> None:
    raise RuntimeError("UUID identifier migration is intentionally irreversible")
