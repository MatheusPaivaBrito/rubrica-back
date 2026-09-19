"""Add monthly file usage tracking for paid plans.

Revision ID: 0015_monthly_file_allowances
Revises: 0014_complimentary_access
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015_monthly_file_allowances"
down_revision: str | None = "0014_complimentary_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_accounts",
        sa.Column(
            "files_uploaded_in_period",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "billing_accounts",
        sa.Column("usage_period_starts_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_billing_accounts_files_uploaded_in_period_nonnegative",
        "billing_accounts",
        "files_uploaded_in_period >= 0",
    )
    op.execute(
        sa.text(
            """
            UPDATE billing_accounts AS account
            SET files_uploaded_in_period = usage.files_uploaded
            FROM (
                SELECT
                    account_count.tenant_id,
                    count(documents.id) AS files_uploaded
                FROM billing_accounts AS account_count
                LEFT JOIN documents
                    ON documents.tenant_id = account_count.tenant_id
                    AND documents.deleted_at IS NULL
                    AND account_count.current_period_ends_at IS NOT NULL
                    AND documents.created_at >= account_count.current_period_ends_at - interval '1 month'
                GROUP BY account_count.tenant_id
            ) AS usage
            WHERE account.tenant_id = usage.tenant_id
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_billing_accounts_files_uploaded_in_period_nonnegative",
        "billing_accounts",
        type_="check",
    )
    op.drop_column("billing_accounts", "usage_period_starts_at")
    op.drop_column("billing_accounts", "files_uploaded_in_period")
