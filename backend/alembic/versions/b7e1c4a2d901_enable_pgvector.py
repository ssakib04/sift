"""enable pgvector extension

Revision ID: b7e1c4a2d901
Revises:
Create Date: 2026-10-06

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7e1c4a2d901"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
