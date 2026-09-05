from alembic import op
import sqlalchemy as sa


revision = "0001_observability_records"
down_revision = None
branch_labels = None
depends_on = None


def _record_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("record_key", sa.String(length=100), primary_key=True),
        sa.Column("service", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "observability_incidents",
        *_record_columns(),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_table(
        "observability_alert_events",
        *_record_columns(),
        sa.Column("rule_code", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=False),
    )
    op.create_table(
        "observability_release_markers",
        *_record_columns(),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("environment", sa.String(length=80), nullable=False),
        sa.Column("commit_sha", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("observability_release_markers")
    op.drop_table("observability_alert_events")
    op.drop_table("observability_incidents")
