"""Add protected international user identifiers.

Revision ID: 0009_user_identifiers
Revises: 0008_mfa_hardening
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0009_user_identifiers"
down_revision: str | None = "0008_mfa_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_identifiers",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuing_country", sa.String(length=2), nullable=False),
        sa.Column("identifier_type", sa.String(length=32), nullable=False),
        sa.Column("normalized_value_encrypted", sa.String(length=512)),
        sa.Column("lookup_hmac", sa.String(length=64)),
        sa.Column("masked_display", sa.String(length=96), nullable=False),
        sa.Column("verification_status", sa.String(length=24), nullable=False),
        sa.Column("verification_method", sa.String(length=48)),
        sa.Column("key_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "identifier_type",
            "issuing_country",
            "lookup_hmac",
            name="uq_user_identifier_lookup",
        ),
    )
    for column in (
        "user_id",
        "issuing_country",
        "identifier_type",
        "lookup_hmac",
        "verification_status",
        "deleted_at",
    ):
        op.create_index(f"ix_user_identifiers_{column}", "user_identifiers", [column])
    op.execute(
        sa.text(
            """
            INSERT INTO user_identifiers (
                user_id, issuing_country, identifier_type, masked_display,
                verification_status, key_version, id
            )
            SELECT id, 'BR', 'BR_CPF', '••••', 'legacy', 1, gen_random_uuid()
            FROM users
            WHERE cpf_hash IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO user_identifiers (
                user_id, issuing_country, identifier_type, masked_display,
                verification_status, key_version, id
            )
            SELECT id, identity_document_country, upper(identity_document_type),
                   '••••' || identity_document_last4, 'legacy', 1, gen_random_uuid()
            FROM users
            WHERE identity_document_hash IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_table("user_identifiers")
