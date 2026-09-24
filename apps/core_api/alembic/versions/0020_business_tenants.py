"""Add business tenants and representation snapshots.

Revision ID: 0020_business_tenants
Revises: 0019_signature_mode
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0020_business_tenants"
down_revision: str | None = "0019_signature_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("kind", sa.String(16), nullable=False, server_default="personal"))
    op.add_column("tenants", sa.Column("legal_name", sa.String(240), nullable=True))
    op.add_column("tenants", sa.Column("registration_country", sa.String(2), nullable=True))
    op.add_column("tenants", sa.Column("registration_type", sa.String(32), nullable=True))
    op.add_column("tenants", sa.Column("registration_value_encrypted", sa.String(512), nullable=True))
    op.add_column("tenants", sa.Column("registration_lookup_hmac", sa.String(64), nullable=True))
    op.add_column("tenants", sa.Column("registration_masked", sa.String(40), nullable=True))
    op.add_column("tenants", sa.Column("registration_verification_status", sa.String(32), nullable=True))
    op.create_index("ix_tenants_kind", "tenants", ["kind"])
    op.create_index(
        "uq_tenants_registration_lookup_active",
        "tenants",
        ["registration_lookup_hmac"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND registration_lookup_hmac IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_tenants_business_identity",
        "tenants",
        "(kind = 'personal') OR (kind = 'business' AND legal_name IS NOT NULL AND registration_country IS NOT NULL AND registration_type IS NOT NULL AND registration_value_encrypted IS NOT NULL AND registration_lookup_hmac IS NOT NULL AND registration_masked IS NOT NULL)",
    )

    op.add_column("tenant_members", sa.Column("auth_user_uuid", sa.Uuid(), nullable=True))
    op.add_column("tenant_members", sa.Column("status", sa.String(16), nullable=False, server_default="active"))
    op.add_column("tenant_members", sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tenant_members_auth_user_uuid", "tenant_members", ["auth_user_uuid"])
    op.create_index("ix_tenant_members_status", "tenant_members", ["status"])

    op.add_column("signature_requests", sa.Column("issuer_snapshot", sa.JSON(), nullable=True))
    op.add_column("signers", sa.Column("participant_role", sa.String(32), nullable=False, server_default="external_signer"))
    op.add_column("signers", sa.Column("represented_tenant_id", sa.Uuid(), nullable=True))
    op.add_column("signers", sa.Column("representation_snapshot", sa.JSON(), nullable=True))
    op.create_foreign_key(
        "fk_signers_represented_tenant",
        "signers",
        "tenants",
        ["represented_tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_signers_participant_role", "signers", ["participant_role"])
    op.create_index("ix_signers_represented_tenant_id", "signers", ["represented_tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_signers_represented_tenant_id", table_name="signers")
    op.drop_index("ix_signers_participant_role", table_name="signers")
    op.drop_constraint("fk_signers_represented_tenant", "signers", type_="foreignkey")
    op.drop_column("signers", "representation_snapshot")
    op.drop_column("signers", "represented_tenant_id")
    op.drop_column("signers", "participant_role")
    op.drop_column("signature_requests", "issuer_snapshot")
    op.drop_index("ix_tenant_members_status", table_name="tenant_members")
    op.drop_index("ix_tenant_members_auth_user_uuid", table_name="tenant_members")
    op.drop_column("tenant_members", "joined_at")
    op.drop_column("tenant_members", "status")
    op.drop_column("tenant_members", "auth_user_uuid")
    op.drop_constraint("ck_tenants_business_identity", "tenants", type_="check")
    op.drop_index("uq_tenants_registration_lookup_active", table_name="tenants")
    op.drop_index("ix_tenants_kind", table_name="tenants")
    for column in (
        "registration_verification_status",
        "registration_masked",
        "registration_lookup_hmac",
        "registration_value_encrypted",
        "registration_type",
        "registration_country",
        "legal_name",
        "kind",
    ):
        op.drop_column("tenants", column)
