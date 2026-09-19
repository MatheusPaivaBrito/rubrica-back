"""Finalize protected identity document storage.

Revision ID: 0010_identifier_protection
Revises: 0009_user_identifiers
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0010_identifier_protection"
down_revision: str | None = "0009_user_identifiers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_user_identifier_protected_or_legacy",
        "user_identifiers",
        "(verification_status = 'legacy' AND normalized_value_encrypted IS NULL "
        "AND lookup_hmac IS NULL) OR "
        "(verification_status <> 'legacy' AND normalized_value_encrypted IS NOT NULL "
        "AND lookup_hmac IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_user_identifier_country_code",
        "user_identifiers",
        "issuing_country ~ '^[A-Z]{2}$'",
    )

    # 0009 preserved one-way legacy hashes long enough to create masked legacy
    # identifier rows. They are no longer used and keeping duplicate document
    # material in users expands the exposure surface.
    op.drop_column("users", "identity_document_last4")
    op.drop_column("users", "identity_document_hash")
    op.drop_column("users", "identity_document_country")
    op.drop_column("users", "identity_document_type")
    op.drop_column("users", "cpf_hash")


def downgrade() -> None:
    op.add_column("users", sa.Column("cpf_hash", sa.String(length=255)))
    op.add_column("users", sa.Column("identity_document_type", sa.String(length=32)))
    op.add_column("users", sa.Column("identity_document_country", sa.String(length=2)))
    op.add_column("users", sa.Column("identity_document_hash", sa.String(length=255)))
    op.add_column("users", sa.Column("identity_document_last4", sa.String(length=4)))
    op.drop_constraint(
        "ck_user_identifier_country_code", "user_identifiers", type_="check"
    )
    op.drop_constraint(
        "ck_user_identifier_protected_or_legacy",
        "user_identifiers",
        type_="check",
    )
