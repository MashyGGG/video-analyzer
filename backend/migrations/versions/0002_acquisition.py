"""Owner-scoped acquisition records; downgrade leaves media volume intact for backup recovery."""

import sqlalchemy as sa
from alembic import op

revision = "0002_acquisition"
down_revision = "0001_installation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acquisition",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("resource", sa.String(200), nullable=False),
        sa.Column("adapter_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("phase", sa.String(10), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("code", sa.String(40), nullable=True),
        sa.Column("info", sa.Text, nullable=False),
        sa.Column("created", sa.BigInteger, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("acquisition")
