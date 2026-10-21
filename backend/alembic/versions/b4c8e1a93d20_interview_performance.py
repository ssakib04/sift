"""interview performance score, separate from the CV score

Revision ID: b4c8e1a93d20
Revises: a8d3c1e54b70
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c8e1a93d20"
down_revision: str | None = "a8d3c1e54b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_performances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("llm_tier", sa.String(length=32), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_table(
        "interview_performance_dimensions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("performance_id", sa.Uuid(), nullable=False),
        sa.Column("dimension_key", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["performance_id"], ["interview_performances.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("performance_id", "dimension_key", name="uq_performance_dimension"),
    )
    op.create_index(
        "ix_interview_performance_dimensions_performance_id",
        "interview_performance_dimensions",
        ["performance_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_performance_dimensions_performance_id",
        table_name="interview_performance_dimensions",
    )
    op.drop_table("interview_performance_dimensions")
    op.drop_table("interview_performances")
