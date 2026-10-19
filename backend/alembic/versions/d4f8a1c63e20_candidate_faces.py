"""candidate face enrollment and interview identification

Revision ID: d4f8a1c63e20
Revises: c7a1e4b82f90
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "d4f8a1c63e20"
down_revision: str | None = "c7a1e4b82f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_sessions",
        sa.Column("biometric_consented_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "candidate_profiles",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("experience_years", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("candidate_id"),
    )
    op.create_table(
        "candidate_faces",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("det_score", sa.Float(), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("candidate_id"),
    )
    op.create_table(
        "face_checks",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("matched_candidate_id", sa.Uuid(), nullable=True),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("invited_similarity", sa.Float(), nullable=True),
        sa.Column("ambiguous", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["matched_candidate_id"], ["candidates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("ix_face_checks_matched_candidate_id", "face_checks", ["matched_candidate_id"])


def downgrade() -> None:
    op.drop_index("ix_face_checks_matched_candidate_id", table_name="face_checks")
    op.drop_table("face_checks")
    op.drop_table("candidate_faces")
    op.drop_table("candidate_profiles")
    op.drop_column("interview_sessions", "biometric_consented_at")
