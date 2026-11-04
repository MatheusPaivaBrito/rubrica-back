from datetime import UTC, datetime
import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_existing_files_keep_legacy_namespace_and_backfill_zero_price(monkeypatch):
    path = Path(__file__).parents[1] / "apps/core_api/alembic/versions/0036_enterprise_usage.py"
    spec = importlib.util.spec_from_file_location("enterprise_usage_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration.context, "is_offline_mode", lambda: False)
    metadata = sa.MetaData()
    integration = sa.Table("enterprise_integrations", metadata,
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid()),
        sa.Column("environment", sa.String()), sa.Column("sandbox", sa.Boolean()))
    compartment = sa.Table("enterprise_compartments", metadata,
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("integration_id", sa.Uuid()))
    documents = sa.Table("enterprise_documents", metadata,
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("compartment_id", sa.Uuid()),
        sa.Column("token_public_id", sa.String()), sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("size_bytes", sa.BigInteger()), sa.Column("deleted_at", sa.DateTime(timezone=True)))
    requests = sa.Table("enterprise_requests", metadata,
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("compartment_id", sa.Uuid()), sa.Column("token_public_id", sa.String()))
    signatures = sa.Table("enterprise_signatures", metadata,
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("request_id", sa.Uuid()),
        sa.Column("signed_at", sa.DateTime(timezone=True)), sa.Column("artifact_size", sa.BigInteger()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)))
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    tenant_id, integration_id, compartment_id, request_id = (uuid4() for _ in range(4))
    with engine.begin() as connection:
        connection.execute(integration.insert(), dict(id=integration_id, tenant_id=tenant_id, environment="development", sandbox=True))
        connection.execute(compartment.insert(), dict(id=compartment_id, integration_id=integration_id))
        connection.execute(documents.insert(), dict(id=uuid4(), compartment_id=compartment_id,
            token_public_id="old-token", created_at=datetime.now(UTC), size_bytes=10))
        connection.execute(requests.insert(), dict(id=request_id, compartment_id=compartment_id, token_public_id="old-token"))
        connection.execute(signatures.insert(), dict(id=uuid4(), request_id=request_id, signed_at=datetime.now(UTC), artifact_size=20))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.scalar(sa.text("SELECT storage_namespace FROM enterprise_documents")) == "legacy"
        assert connection.scalar(sa.text("SELECT storage_namespace FROM enterprise_signatures")) == "legacy"
        assert connection.scalar(sa.text("SELECT count(*) FROM enterprise_usage_events")) == 2
        assert connection.scalar(sa.text("SELECT count(*) FROM enterprise_telemetry_outbox")) == 2
        assert connection.scalar(sa.text("SELECT sum(amount_minor) FROM enterprise_usage_events")) == 0
        assert connection.scalar(sa.text("SELECT storage_bytes FROM enterprise_quotas")) == 30
        assert connection.scalar(sa.text("SELECT document_count FROM enterprise_quotas")) == 1
