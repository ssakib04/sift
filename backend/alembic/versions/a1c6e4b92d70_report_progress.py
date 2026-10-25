"""remember which post-call reports are still being written

Revision ID: a1c6e4b92d70
Revises: f4a9c2e81b30
Create Date: 2026-10-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c6e4b92d70"
down_revision: str | None = "f4a9c2e81b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_sessions",
        sa.Column("report_progress", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("interview_sessions", "report_progress")
