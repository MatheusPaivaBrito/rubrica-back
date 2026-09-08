"""Migrate Core entity identifiers and foreign keys to UUIDs."""

from alembic import op
import sqlalchemy as sa


revision = "0007_uuid_identifiers"
down_revision = "0006_tenants_billing"
branch_labels = None
depends_on = None


def _uuid(expression: str) -> str:
    return f"('00000000-0000-0000-0000-' || lpad(to_hex({expression}), 12, '0'))::uuid"


def upgrade() -> None:
    foreign_keys = (
        ("document_versions_document_id_fkey", "document_versions"),
        ("signature_requests_document_id_fkey", "signature_requests"),
        ("signers_signature_request_id_fkey", "signers"),
        ("signatures_signature_request_id_fkey", "signatures"),
        ("signatures_signer_id_fkey", "signatures"),
        ("audit_events_signature_request_id_fkey", "audit_events"),
        ("tenant_members_tenant_id_fkey", "tenant_members"),
        ("fk_documents_tenant", "documents"),
        ("billing_accounts_tenant_id_fkey", "billing_accounts"),
        ("billing_events_tenant_id_fkey", "billing_events"),
    )
    for constraint, table in foreign_keys:
        op.drop_constraint(constraint, table, type_="foreignkey")

    for table in ("documents", "document_versions", "signature_requests", "signers", "signatures", "audit_events", "tenants", "tenant_members", "billing_accounts", "billing_events"):
        op.alter_column(table, "id", server_default=None)
        op.alter_column(table, "id", type_=sa.Uuid(), postgresql_using=_uuid("id"))

    columns = (
        ("document_versions", "document_id"),
        ("signature_requests", "document_id"),
        ("signers", "signature_request_id"),
        ("signatures", "signature_request_id"),
        ("signatures", "signer_id"),
        ("audit_events", "signature_request_id"),
        ("tenant_members", "tenant_id"),
        ("documents", "tenant_id"),
        ("billing_accounts", "tenant_id"),
        ("billing_events", "tenant_id"),
    )
    for table, column in columns:
        op.alter_column(table, column, type_=sa.Uuid(), postgresql_using=_uuid(column))

    op.alter_column("audit_events", "entity_id", type_=sa.Uuid(), postgresql_using=_uuid("entity_id::bigint"))
    op.alter_column("audit_events", "correlation_id", type_=sa.Uuid(), postgresql_using="correlation_id::uuid")

    op.create_foreign_key("document_versions_document_id_fkey", "document_versions", "documents", ["document_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("signature_requests_document_id_fkey", "signature_requests", "documents", ["document_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("signers_signature_request_id_fkey", "signers", "signature_requests", ["signature_request_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("signatures_signature_request_id_fkey", "signatures", "signature_requests", ["signature_request_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("signatures_signer_id_fkey", "signatures", "signers", ["signer_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("audit_events_signature_request_id_fkey", "audit_events", "signature_requests", ["signature_request_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("tenant_members_tenant_id_fkey", "tenant_members", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_documents_tenant", "documents", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("billing_accounts_tenant_id_fkey", "billing_accounts", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("billing_events_tenant_id_fkey", "billing_events", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")

    # Reconcile indexes declared by the ORM but absent from the historical
    # hand-written migrations. Unique indexed columns use one database object,
    # avoiding a duplicate unique constraint plus non-unique index.
    op.drop_constraint("tenants_slug_key", "tenants", type_="unique")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)
    op.drop_constraint("billing_accounts_tenant_id_key", "billing_accounts", type_="unique")
    op.drop_index("ix_billing_accounts_tenant_id", table_name="billing_accounts")
    op.create_index(
        "ix_billing_accounts_tenant_id",
        "billing_accounts",
        ["tenant_id"],
        unique=True,
    )

    indexes = {
        "audit_events": (
            "action",
            "actor_id",
            "correlation_id",
            "deleted_at",
            "entity_id",
            "entity_type",
            "occurred_at",
            "signature_request_id",
        ),
        "document_versions": ("deleted_at", "document_id", "sha256"),
        "documents": (
            "created_by",
            "deleted_at",
            "organization_id",
            "sha256",
            "status",
            "title",
        ),
        "signature_requests": (
            "created_by",
            "deleted_at",
            "document_id",
            "document_sha256",
            "expires_at",
            "status",
        ),
        "signatures": (
            "auth_user_id",
            "deleted_at",
            "signature_request_id",
            "signer_id",
        ),
        "signers": (
            "auth_user_id",
            "deleted_at",
            "email",
            "signature_request_id",
            "status",
            "token_expires_at",
        ),
    }
    for table, columns_to_index in indexes.items():
        for column in columns_to_index:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    raise RuntimeError("UUID identifier migration is intentionally irreversible")
