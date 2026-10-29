"""Persist the number of contracted workspace seats.

Revision ID: 0030_billing_contracted_seats
Revises: 0029_signature_request_opened_at
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_billing_contracted_seats"
down_revision = "0029_signature_request_opened_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "billing_accounts",
        sa.Column(
            "contracted_seats",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.execute(
        """
        UPDATE billing_accounts
        SET contracted_seats = CASE
            WHEN complimentary_lifetime THEN 10
            WHEN current_product_code = 'rubrica_team' THEN 10
            WHEN current_product_code = 'rubrica_intermediate' THEN 3
            ELSE 1
        END
        """
    )
    op.create_check_constraint(
        "ck_billing_accounts_contracted_seats_positive",
        "billing_accounts",
        "contracted_seats >= 1",
    )
    op.alter_column(
        "signers",
        "signature_mode",
        server_default="evidence",
        existing_type=sa.String(length=30),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "signers",
        "signature_mode",
        server_default="serpro_timestamp",
        existing_type=sa.String(length=30),
        existing_nullable=False,
    )
    op.drop_constraint(
        "ck_billing_accounts_contracted_seats_positive",
        "billing_accounts",
        type_="check",
    )
    op.drop_column("billing_accounts", "contracted_seats")
