"""Make document versions, signatures and audit events append only.

Revision ID: 0024_immutable_signature_records
Revises: 0023_stripe_business_identity
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0024_immutable_signature_records"
down_revision: str | None = "0023_stripe_business_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


IMMUTABLE_TABLES = ("document_versions", "signatures", "audit_events")


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION rubrica_reject_immutable_record_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only; % is forbidden', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION rubrica_reject_immutable_record_change()
            """
        )


def downgrade() -> None:
    for table in reversed(IMMUTABLE_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS rubrica_reject_immutable_record_change()")
