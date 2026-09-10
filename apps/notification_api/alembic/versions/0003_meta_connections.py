from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_meta_connections"
down_revision = "0002_uuid_identifiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meta_whatsapp_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("waba_id", sa.String(length=80), nullable=False),
        sa.Column("phone_number_id", sa.String(length=80), nullable=False),
        sa.Column("display_phone_number", sa.String(length=40), nullable=True),
        sa.Column("verified_name", sa.String(length=255), nullable=True),
        sa.Column("quality_rating", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "phone_number_id",
            name="uq_meta_whatsapp_connections_phone_number",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            name="uq_meta_whatsapp_connections_tenant",
        ),
    )
    op.create_index(
        "ix_meta_whatsapp_connections_status",
        "meta_whatsapp_connections",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_meta_whatsapp_connections_status",
        table_name="meta_whatsapp_connections",
    )
    op.drop_table("meta_whatsapp_connections")
