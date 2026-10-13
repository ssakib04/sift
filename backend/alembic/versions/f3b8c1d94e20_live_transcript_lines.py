"""mark a transcript line as still being spoken or finished

Revision ID: f3b8c1d94e20
Revises: e7c1a4b82d30
Create Date: 2026-10-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8c1d94e20"
down_revision: str | None = "e7c1a4b82d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcript_segments",
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("transcript_segments", "is_final")
