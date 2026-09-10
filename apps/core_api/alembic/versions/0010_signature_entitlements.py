"""Add the tenant signature entitlement counter.

Revision ID: 0010_signature_entitlements
Revises: 0009_stripe_subscription
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0010_signature_entitlements"
down_revision: str | None = "0009_stripe_subscription"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_accounts",
        sa.Column(
            "free_signatures_limit",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
    )
    op.add_column(
        "billing_accounts",
        sa.Column(
            "signatures_used",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO billing_accounts (
                tenant_id,
                status,
                free_signatures_limit,
                signatures_used
            )
            SELECT tenants.id, 'not_configured', 5, 0
            FROM tenants
            LEFT JOIN billing_accounts
                ON billing_accounts.tenant_id = tenants.id
            WHERE billing_accounts.id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE billing_accounts
            SET signatures_used = historical.completed_signatures
            FROM (
                SELECT documents.tenant_id, count(signatures.id) AS completed_signatures
                FROM signatures
                JOIN signature_requests
                    ON signature_requests.id = signatures.signature_request_id
                JOIN documents
                    ON documents.id = signature_requests.document_id
                GROUP BY documents.tenant_id
            ) AS historical
            WHERE billing_accounts.tenant_id = historical.tenant_id
            """
        )
    )
    op.create_check_constraint(
        "ck_billing_accounts_free_signatures_limit_nonnegative",
        "billing_accounts",
        "free_signatures_limit >= 0",
    )
    op.create_check_constraint(
        "ck_billing_accounts_signatures_used_nonnegative",
        "billing_accounts",
        "signatures_used >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_billing_accounts_signatures_used_nonnegative",
        "billing_accounts",
        type_="check",
    )
    op.drop_constraint(
        "ck_billing_accounts_free_signatures_limit_nonnegative",
        "billing_accounts",
        type_="check",
    )
    op.drop_column("billing_accounts", "signatures_used")
    op.drop_column("billing_accounts", "free_signatures_limit")
