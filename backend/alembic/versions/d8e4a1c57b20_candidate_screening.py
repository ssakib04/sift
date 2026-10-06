"""candidate screening tables

Revision ID: d8e4a1c57b20
Revises: c3a91e7b2f10
Create Date: 2026-10-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8e4a1c57b20"
down_revision: str | None = "c3a91e7b2f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("mail_subject", sa.String(length=255), nullable=True))
    op.execute("UPDATE jobs SET mail_subject = title WHERE mail_subject IS NULL")
    op.alter_column("jobs", "mail_subject", nullable=False)

    op.create_table(
        "candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_version_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_message_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_version_id", "content_sha256", name="uq_candidate_version_sha"),
    )
    op.create_index("ix_candidates_job_version_id", "candidates", ["job_version_id"])
    op.create_table(
        "candidate_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=127), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id"),
    )
    op.create_table(
        "candidate_parse_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("parse_method", sa.String(length=32), nullable=False),
        sa.Column("parse_confidence", sa.Float(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id"),
    )
    op.create_table(
        "score_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_version_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_score", sa.Float(), nullable=False),
        sa.Column("must_have_ratio", sa.Float(), nullable=False),
        sa.Column("technical_score", sa.Float(), nullable=False),
        sa.Column("experience_score", sa.Float(), nullable=False),
        sa.Column("qualification_score", sa.Float(), nullable=False),
        sa.Column("fairness_flags", sa.JSON(), nullable=False),
        sa.Column("justifications", sa.JSON(), nullable=False),
        sa.Column("llm_tier", sa.String(length=32), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id"),
    )
    op.create_index("ix_score_snapshots_job_version_id", "score_snapshots", ["job_version_id"])
    op.create_table(
        "query_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("query_id", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("semantic_score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["score_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "query_id", name="uq_snapshot_query"),
    )
    op.create_index("ix_query_evaluations_snapshot_id", "query_evaluations", ["snapshot_id"])
    op.create_table(
        "magic_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id"),
        sa.UniqueConstraint("token"),
    )
    op.create_table(
        "interview_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id"),
    )
    op.create_index("ix_interview_sessions_job_version_id", "interview_sessions", ["job_version_id"])
    op.create_table(
        "intake_messages",
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("job_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("message_id"),
    )


def downgrade() -> None:
    op.drop_table("intake_messages")
    op.drop_index("ix_interview_sessions_job_version_id", table_name="interview_sessions")
    op.drop_table("interview_sessions")
    op.drop_table("magic_links")
    op.drop_index("ix_query_evaluations_snapshot_id", table_name="query_evaluations")
    op.drop_table("query_evaluations")
    op.drop_index("ix_score_snapshots_job_version_id", table_name="score_snapshots")
    op.drop_table("score_snapshots")
    op.drop_table("candidate_parse_results")
    op.drop_table("candidate_documents")
    op.drop_index("ix_candidates_job_version_id", table_name="candidates")
    op.drop_table("candidates")
    op.drop_column("jobs", "mail_subject")
