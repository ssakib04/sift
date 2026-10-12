"""interview transcript and post-call analysis

Revision ID: e7c1a4b82d30
Revises: d8e4a1c57b20
Create Date: 2026-10-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7c1a4b82d30"
down_revision: str | None = "d8e4a1c57b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("interview_sessions", sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interview_sessions", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("interview_sessions", sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "interview_sessions",
        sa.Column("processing_status", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "interview_sessions",
        sa.Column("copilot_explored", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "interview_sessions",
        sa.Column("copilot_gaps", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "interview_sessions",
        sa.Column("copilot_question", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "interview_sessions",
        sa.Column("copilot_turn_count", sa.Integer(), nullable=False, server_default="-1"),
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("speaker", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transcript_segments_session_id", "transcript_segments", ["session_id"])
    op.create_table(
        "interview_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=False),
        sa.Column("technical_accuracy", sa.Float(), nullable=False),
        sa.Column("completeness", sa.Float(), nullable=False),
        sa.Column("articulation", sa.Float(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("llm_tier", sa.String(length=32), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )


def downgrade() -> None:
    op.drop_table("interview_analyses")
    op.drop_index("ix_transcript_segments_session_id", table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_column("interview_sessions", "copilot_turn_count")
    op.drop_column("interview_sessions", "copilot_question")
    op.drop_column("interview_sessions", "copilot_gaps")
    op.drop_column("interview_sessions", "copilot_explored")
    op.drop_column("interview_sessions", "processing_status")
    op.drop_column("interview_sessions", "ended_at")
    op.drop_column("interview_sessions", "started_at")
    op.drop_column("interview_sessions", "consented_at")
