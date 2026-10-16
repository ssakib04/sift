"""skill quiz attempts

Revision ID: a9c4e2b71d50
Revises: f3b8c1d94e20
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c4e2b71d50"
down_revision: str | None = "f3b8c1d94e20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcq_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_version_id", sa.Uuid(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.Column("correct_count", sa.Integer(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=False),
        sa.Column("llm_tier", sa.String(length=32), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id"),
    )
    op.create_index("ix_mcq_attempts_job_version_id", "mcq_attempts", ["job_version_id"])


def downgrade() -> None:
    op.drop_index("ix_mcq_attempts_job_version_id", table_name="mcq_attempts")
    op.drop_table("mcq_attempts")
