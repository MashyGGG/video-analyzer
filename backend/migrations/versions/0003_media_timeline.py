"""Owner-scoped A03 timeline job status."""

import sqlalchemy as sa
from alembic import op

revision = "0003_media_timeline"
down_revision = "0002_acquisition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_timeline",
        sa.Column("asset_id", sa.String(36), primary_key=True),
        sa.Column("attempt", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("code", sa.String(40)),
        sa.Column("updated", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["acquisition.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("media_timeline")
