"""Use EUR for existing euro-market tenants still on the USD default.

Revision ID: 0013_euro_tenant_currency
Revises: 0012_billing_payments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013_euro_tenant_currency"
down_revision: str | None = "0012_billing_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


EURO_COUNTRY_CODES = (
    "AD", "AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR",
    "IE", "IT", "LT", "LU", "LV", "MC", "ME", "MT", "NL", "PT", "SI",
    "SK", "SM", "VA", "XK",
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tenants SET currency = 'EUR' "
            "WHERE currency = 'USD' AND country_code IN :country_codes"
        ).bindparams(sa.bindparam("country_codes", expanding=True, value=EURO_COUNTRY_CODES))
    )


def downgrade() -> None:
    # Currency can be changed by an administrator after this migration. Reverting
    # those choices would corrupt billing configuration, so the data change stays.
    pass
