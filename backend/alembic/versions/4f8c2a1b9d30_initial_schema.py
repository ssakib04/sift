"""Initial screening schema.

Revision ID: 4f8c2a1b9d30
Revises:
Create Date: 2026-10-04 17:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "4f8c2a1b9d30"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIMENSIONS = 384


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.create_table(
        "job_profile",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "candidate",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidate_email", "candidate", ["email"], unique=True)
    op.create_table(
        "cv",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidate.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cv_candidate_id", "cv", ["candidate_id"], unique=False)
    op.create_table(
        "score",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_profile_id", sa.Uuid(), nullable=False),
        sa.Column("dimensional_scores", sa.JSON(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidate.id"]),
        sa.ForeignKeyConstraint(["job_profile_id"], ["job_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_score_candidate_id", "score", ["candidate_id"], unique=False)
    op.create_index("ix_score_job_profile_id", "score", ["job_profile_id"], unique=False)
    op.create_table(
        "session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_profile_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidate.id"]),
        sa.ForeignKeyConstraint(["job_profile_id"], ["job_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_candidate_id", "session", ["candidate_id"], unique=False)
    op.create_index("ix_session_job_profile_id", "session", ["job_profile_id"], unique=False)
    op.create_table(
        "transcript",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("speaker", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("timestamp_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transcript_session_id", "transcript", ["session_id"], unique=False)
    op.create_table(
        "assessment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("consolidated_report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assessment_session_id", "assessment", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_assessment_session_id", table_name="assessment")
    op.drop_table("assessment")
    op.drop_index("ix_transcript_session_id", table_name="transcript")
    op.drop_table("transcript")
    op.drop_index("ix_session_job_profile_id", table_name="session")
    op.drop_index("ix_session_candidate_id", table_name="session")
    op.drop_table("session")
    op.drop_index("ix_score_job_profile_id", table_name="score")
    op.drop_index("ix_score_candidate_id", table_name="score")
    op.drop_table("score")
    op.drop_index("ix_cv_candidate_id", table_name="cv")
    op.drop_table("cv")
    op.drop_index("ix_candidate_email", table_name="candidate")
    op.drop_table("candidate")
    op.drop_table("job_profile")
