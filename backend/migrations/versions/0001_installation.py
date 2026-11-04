"""Initial infrastructure schema, no inherited business tables."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0001_installation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "installation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.bulk_insert(table, [{"id": uuid4()}])


def downgrade() -> None:
    # Destructive; only after backup. A01 acceptance uses a separate disposable database.
    op.drop_table("installation")
