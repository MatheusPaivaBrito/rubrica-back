"""Closure receipts and narrowly constrained enterprise audit anonymization."""
from alembic import op
import sqlalchemy as sa

revision = "0040_enterprise_closure"
down_revision = "0039_enterprise_lifecycle"
branch_labels = depends_on = None


def upgrade():
    op.create_table("enterprise_closures", sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)), sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        *[sa.Column(name, sa.DateTime(timezone=True)) for name in ("metadata_purged_at", "objects_verified_at", "credentials_retired_at", "backups_verified_at", "reopened_at")],
        sa.Column("backup_receipt", sa.JSON()), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False), sa.Column("error_code", sa.String(80)),
        sa.UniqueConstraint("tenant_id", "revision", name="uq_enterprise_closure_revision"))
    op.create_index("ix_enterprise_closures_deleted_at", "enterprise_closures", ["deleted_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE OR REPLACE FUNCTION rubrica_reject_immutable_record_change()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_TABLE_NAME = 'audit_events' AND TG_OP = 'UPDATE' THEN
            IF OLD.action LIKE 'enterprise.%' AND OLD.entity_type = 'tenant'
              AND NEW.actor_id = '[erased]' AND NEW.metadata_sanitized::jsonb = '{}'::jsonb
              AND (to_jsonb(NEW) - ARRAY['actor_id','metadata_sanitized','updated_at']) =
                  (to_jsonb(OLD) - ARRAY['actor_id','metadata_sanitized','updated_at'])
              AND EXISTS (SELECT 1 FROM enterprise_lifecycle l WHERE l.tenant_id = OLD.entity_id
                AND l.purged_at IS NOT NULL AND l.recovery_until <= clock_timestamp())
            THEN RETURN NEW; END IF;
          END IF;
          RAISE EXCEPTION '% is append-only; % is forbidden', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'integrity_constraint_violation';
        END; $$""")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE OR REPLACE FUNCTION rubrica_reject_immutable_record_change()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION '% is append-only; % is forbidden', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'integrity_constraint_violation'; END; $$""")
    op.drop_table("enterprise_closures")
