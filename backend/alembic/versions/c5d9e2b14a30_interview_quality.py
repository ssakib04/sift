"""interview process quality, separate from the candidate score

Revision ID: c5d9e2b14a30
Revises: b4c8e1a93d20
Create Date: 2026-10-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d9e2b14a30"
down_revision: str | None = "b4c8e1a93d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_qualities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("interviewer_share", sa.Float(), nullable=False),
        sa.Column("candidate_share", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_table(
        "interview_quality_dimensions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quality_id", sa.Uuid(), nullable=False),
        sa.Column("dimension_key", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["quality_id"], ["interview_qualities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quality_id", "dimension_key", name="uq_quality_dimension"),
    )
    op.create_index("ix_interview_quality_dimensions_quality_id", "interview_quality_dimensions", ["quality_id"])
    op.create_table(
        "interview_quality_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quality_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["quality_id"], ["interview_qualities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_interview_quality_recommendations_quality_id",
        "interview_quality_recommendations",
        ["quality_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_interview_quality_recommendations_quality_id", table_name="interview_quality_recommendations")
    op.drop_table("interview_quality_recommendations")
    op.drop_index("ix_interview_quality_dimensions_quality_id", table_name="interview_quality_dimensions")
    op.drop_table("interview_quality_dimensions")
    op.drop_table("interview_qualities")
