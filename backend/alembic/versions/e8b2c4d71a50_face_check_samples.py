"""store a short run of face checks before a conclusion

Revision ID: e8b2c4d71a50
Revises: d4f8a1c63e20
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b2c4d71a50"
down_revision: str | None = "d4f8a1c63e20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "face_checks",
        sa.Column("samples", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "face_checks",
        sa.Column("concluded", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("face_checks", "concluded")
    op.drop_column("face_checks", "samples")
