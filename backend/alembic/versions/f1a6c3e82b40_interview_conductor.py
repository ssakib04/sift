"""who conducts the interview

Revision ID: f1a6c3e82b40
Revises: a7c3e91b4d20
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a6c3e82b40"
down_revision: str | None = "a7c3e91b4d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_sessions",
        sa.Column("conductor", sa.String(length=16), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("interview_sessions", "conductor")
