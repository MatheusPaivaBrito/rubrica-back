"""Auth-owned machine credentials and atomic rotation audit."""

from alembic import op
import sqlalchemy as sa

revision = "0013_machine_credentials"
down_revision = "0012_local_mfa_exemption"
branch_labels = None
depends_on = None


def common_columns():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "machine_credentials", *common_columns(),
        sa.Column("environment", sa.String(24), nullable=False),
        sa.Column("sandbox", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("public_id", sa.String(32), unique=True),
        sa.Column("digest", sa.String(64)),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        sa.Column("rotated_by", sa.String(255)),
        sa.UniqueConstraint("integration_id", "environment", "sandbox", name="uq_machine_integration_environment"),
    )
    op.create_table(
        "machine_credential_audit", *common_columns(),
        sa.Column("public_id", sa.String(32)),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
    )
    for table in ("machine_credentials", "machine_credential_audit"):
        for column in ("tenant_id", "deleted_at"):
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    op.drop_table("machine_credential_audit")
    op.drop_table("machine_credentials")
