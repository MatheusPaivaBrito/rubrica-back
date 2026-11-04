"""Canonical zero-price usage ledger, telemetry outbox and isolated quotas."""
from alembic import context, op
import sqlalchemy as sa
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

revision = "0036_enterprise_usage"
down_revision = "0035_enterprise_workflows"
branch_labels = None
depends_on = None


def base():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True))]


def upgrade():
    for table in ("enterprise_documents", "enterprise_signatures"):
        op.add_column(table, sa.Column("storage_namespace", sa.String(24), nullable=False, server_default="legacy"))
    op.create_table("enterprise_usage_events", *base(),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("compartment_id", sa.Uuid(), nullable=False),
        sa.Column("token_public_id", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(24), nullable=False),
        sa.Column("sandbox", sa.Boolean(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("bytes_count", sa.BigInteger(), nullable=False),
        sa.Column("billable", sa.Boolean(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("price_version", sa.String(40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer()), sa.Column("duration_ms", sa.Float()),
        sa.UniqueConstraint("kind", "source_id", name="uq_enterprise_usage_source"))
    op.create_table("enterprise_telemetry_outbox", *base(),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("enterprise_usage_events.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("enterprise_quotas", *base(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False), sa.Column("sandbox", sa.Boolean(), nullable=False),
        *[sa.Column(name, sa.BigInteger() if name in {"storage_bytes", "signing_day"} else sa.Integer(), nullable=False)
          for name in ("storage_bytes", "document_count", "signing_day", "signing_count")],
        sa.UniqueConstraint("tenant_id", "sandbox", name="uq_enterprise_quota_mode"))
    op.create_table("enterprise_api_rate_buckets", *base(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False), sa.Column("sandbox", sa.Boolean(), nullable=False),
        sa.Column("minute", sa.BigInteger(), nullable=False), sa.Column("count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "sandbox", name="uq_enterprise_rate_mode"))
    for table in ("enterprise_usage_events", "enterprise_telemetry_outbox", "enterprise_quotas", "enterprise_api_rate_buckets"):
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])
    for column in ("tenant_id", "integration_id", "occurred_at"):
        op.create_index(f"ix_enterprise_usage_events_{column}", "enterprise_usage_events", [column])
    op.create_index("ix_enterprise_telemetry_outbox_next_attempt_at", "enterprise_telemetry_outbox", ["next_attempt_at"])
    if not context.is_offline_mode():
        backfill_existing_usage()


def backfill_existing_usage():
    """Preserve pre-metering files and facts without creating retroactive debt."""
    connection = op.get_bind()
    events = sa.table("enterprise_usage_events", *[
        sa.column(name, kind) for name, kind in (
            ("id", sa.Uuid()), ("source_id", sa.Uuid()), ("tenant_id", sa.Uuid()),
            ("integration_id", sa.Uuid()), ("compartment_id", sa.Uuid()),
            ("token_public_id", sa.String()), ("environment", sa.String()), ("sandbox", sa.Boolean()),
            ("kind", sa.String()), ("units", sa.Integer()), ("bytes_count", sa.BigInteger()),
            ("billable", sa.Boolean()), ("amount_minor", sa.Integer()), ("currency", sa.String()),
            ("price_version", sa.String()), ("occurred_at", sa.DateTime(timezone=True)))])
    outbox = sa.table("enterprise_telemetry_outbox", sa.column("id", sa.Uuid()),
        sa.column("event_id", sa.Uuid()), sa.column("attempts", sa.Integer()),
        sa.column("next_attempt_at", sa.DateTime(timezone=True)))
    quotas = sa.table("enterprise_quotas", sa.column("id", sa.Uuid()), sa.column("tenant_id", sa.Uuid()),
        sa.column("sandbox", sa.Boolean()), sa.column("storage_bytes", sa.BigInteger()),
        sa.column("document_count", sa.Integer()), sa.column("signing_day", sa.BigInteger()), sa.column("signing_count", sa.Integer()))
    now = datetime.now(UTC)
    rows = connection.execute(sa.text("""
        SELECT d.id AS source_id, i.tenant_id, i.id AS integration_id, c.id AS compartment_id,
               d.token_public_id, i.environment, i.sandbox, d.created_at AS occurred_at,
               d.size_bytes AS bytes_count, 'document.uploaded' AS kind
        FROM enterprise_documents d JOIN enterprise_compartments c ON c.id=d.compartment_id
        JOIN enterprise_integrations i ON i.id=c.integration_id WHERE d.deleted_at IS NULL
        UNION ALL
        SELECT s.id, i.tenant_id, i.id, c.id, r.token_public_id, i.environment, i.sandbox,
               s.signed_at, s.artifact_size, 'signature.completed'
        FROM enterprise_signatures s JOIN enterprise_requests r ON r.id=s.request_id
        JOIN enterprise_compartments c ON c.id=r.compartment_id
        JOIN enterprise_integrations i ON i.id=c.integration_id WHERE s.deleted_at IS NULL
    """))
    batch, jobs, counters = [], [], {}
    for row in rows.mappings():
        source_id = UUID(str(row["source_id"]))
        tenant_id = UUID(str(row["tenant_id"]))
        sandbox = bool(row["sandbox"])
        occurred = row["occurred_at"]
        if isinstance(occurred, str):
            occurred = datetime.fromisoformat(occurred)
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=UTC)
        event_id = uuid5(NAMESPACE_URL, f"rubrica.enterprise.{row['kind']}:{source_id}")
        batch.append(dict(id=event_id, source_id=source_id, tenant_id=tenant_id,
            integration_id=UUID(str(row["integration_id"])), compartment_id=UUID(str(row["compartment_id"])),
            token_public_id=row["token_public_id"], environment=row["environment"], sandbox=sandbox,
            kind=row["kind"], units=1, bytes_count=row["bytes_count"],
            billable=not sandbox and row["kind"] == "signature.completed", amount_minor=0,
            currency="BRL", price_version="enterprise-zero-v1", occurred_at=occurred))
        jobs.append(dict(id=uuid4(), event_id=event_id, attempts=0, next_attempt_at=now))
        counter = counters.setdefault((tenant_id, sandbox), dict(id=uuid4(), tenant_id=tenant_id,
            sandbox=sandbox, storage_bytes=0, document_count=0,
            signing_day=int(now.timestamp()) // 86400, signing_count=0))
        counter["storage_bytes"] += row["bytes_count"]
        counter["document_count"] += row["kind"] == "document.uploaded"
        if row["kind"] == "signature.completed" and occurred.date() == now.date():
            counter["signing_count"] += 1
        if len(batch) == 50:
            connection.execute(events.insert(), batch)
            connection.execute(outbox.insert(), jobs)
            batch, jobs = [], []
    if batch:
        connection.execute(events.insert(), batch)
        connection.execute(outbox.insert(), jobs)
    if counters:
        connection.execute(quotas.insert(), list(counters.values()))


def downgrade():
    for table in ("enterprise_api_rate_buckets", "enterprise_quotas", "enterprise_telemetry_outbox", "enterprise_usage_events"):
        op.drop_table(table)
    for table in ("enterprise_documents", "enterprise_signatures"):
        op.drop_column(table, "storage_namespace")
