"""applicant notices and interview schedule

Revision ID: a8d3c1e54b70
Revises: f1a6c3e82b40
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8d3c1e54b70"
down_revision: str | None = "f1a6c3e82b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("interview_sessions", sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interview_sessions", sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "interview_sessions",
        sa.Column("calendar_event_id", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "interview_sessions",
        sa.Column("calendar_url", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "applicant_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id"),
    )


def downgrade() -> None:
    op.drop_table("applicant_notifications")
    op.drop_column("interview_sessions", "calendar_url")
    op.drop_column("interview_sessions", "calendar_event_id")
    op.drop_column("interview_sessions", "scheduled_end")
    op.drop_column("interview_sessions", "scheduled_start")
