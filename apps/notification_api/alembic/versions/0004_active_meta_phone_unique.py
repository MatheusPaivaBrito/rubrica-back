from alembic import op
import sqlalchemy as sa


revision = "0004_active_meta_phone_unique"
down_revision = "0003_meta_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_meta_whatsapp_connections_phone_number",
        "meta_whatsapp_connections",
        type_="unique",
    )
    op.create_index(
        "uq_meta_whatsapp_connections_connected_phone",
        "meta_whatsapp_connections",
        ["phone_number_id"],
        unique=True,
        postgresql_where=sa.text("status = 'connected'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_meta_whatsapp_connections_connected_phone",
        table_name="meta_whatsapp_connections",
    )
    op.create_unique_constraint(
        "uq_meta_whatsapp_connections_phone_number",
        "meta_whatsapp_connections",
        ["phone_number_id"],
    )
