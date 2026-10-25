"""recruiter admission when a face check does not match

Revision ID: f4a9c2e81b30
Revises: e3c8b5d92f10
Create Date: 2026-10-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a9c2e81b30"
down_revision: str | None = "e3c8b5d92f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_sessions",
        sa.Column("face_admitted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interview_sessions", "face_admitted_at")
