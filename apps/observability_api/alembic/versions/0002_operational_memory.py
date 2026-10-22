from alembic import op
import sqlalchemy as sa


revision = "0002_operational_memory"
down_revision = "0001_observability_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "observability_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("service_name", sa.String(length=120), nullable=False),
        sa.Column("environment", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("collect_logs", sa.Boolean(), nullable=False),
        sa.Column("collect_metrics", sa.Boolean(), nullable=False),
        sa.Column("collect_traces", sa.Boolean(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_observability_sources_tenant_service",
        "observability_sources",
        ["tenant_id", "service_name"],
    )
    op.create_table(
        "monitoring_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("signal_type", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["observability_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_monitoring_policies_source_enabled",
        "monitoring_policies",
        ["source_id", "enabled"],
    )
    op.create_table(
        "observability_incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("external_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["observability_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_fingerprint"),
    )
    op.create_index(
        "ix_observability_incidents_source_last_seen",
        "observability_incidents",
        ["source_id", "last_seen_at"],
    )
    op.create_index(
        "ix_observability_incidents_status_severity",
        "observability_incidents",
        ["status", "severity"],
    )
    op.create_table(
        "observability_incident_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["observability_incidents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_incident_events_incident_observed",
        "observability_incident_events",
        ["incident_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_incident_events_incident_observed", table_name="observability_incident_events")
    op.drop_table("observability_incident_events")
    op.drop_index("ix_observability_incidents_status_severity", table_name="observability_incidents")
    op.drop_index("ix_observability_incidents_source_last_seen", table_name="observability_incidents")
    op.drop_table("observability_incidents")
    op.drop_index("ix_monitoring_policies_source_enabled", table_name="monitoring_policies")
    op.drop_table("monitoring_policies")
    op.drop_index("ix_observability_sources_tenant_service", table_name="observability_sources")
    op.drop_table("observability_sources")
