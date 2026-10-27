"""remember when a finished candidate was sent an approval mail

Revision ID: b6d2f8a41c90
Revises: a1c6e4b92d70
Create Date: 2026-10-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6d2f8a41c90"
down_revision: str | None = "a1c6e4b92d70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("approval_mailed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidates", "approval_mailed_at")
