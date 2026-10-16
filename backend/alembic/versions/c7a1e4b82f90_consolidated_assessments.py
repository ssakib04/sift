"""consolidated candidate assessments

Revision ID: c7a1e4b82f90
Revises: b2e8c4a91d60
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7a1e4b82f90"
down_revision: str | None = "b2e8c4a91d60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consolidated_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_version_id", sa.Uuid(), nullable=False),
        sa.Column("overall_suitability", sa.String(length=32), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("cv_weight", sa.Float(), nullable=False),
        sa.Column("mcq_weight", sa.Float(), nullable=False),
        sa.Column("interview_weight", sa.Float(), nullable=False),
        sa.Column("llm_tier", sa.String(length=32), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id"),
    )
    op.create_index("ix_consolidated_assessments_job_version_id", "consolidated_assessments", ["job_version_id"])
    op.create_table(
        "assessment_component_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("component", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["assessment_id"], ["consolidated_assessments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "component", name="uq_assessment_component"),
    )
    op.create_index("ix_assessment_component_scores_assessment_id", "assessment_component_scores", ["assessment_id"])
    op.create_table(
        "assessment_strengths",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["consolidated_assessments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assessment_strengths_assessment_id", "assessment_strengths", ["assessment_id"])
    op.create_table(
        "assessment_weaknesses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["consolidated_assessments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assessment_weaknesses_assessment_id", "assessment_weaknesses", ["assessment_id"])
    op.create_table(
        "evidence_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assessment_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_reference", sa.String(length=80), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["consolidated_assessments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_links_assessment_id", "evidence_links", ["assessment_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_links_assessment_id", table_name="evidence_links")
    op.drop_table("evidence_links")
    op.drop_index("ix_assessment_weaknesses_assessment_id", table_name="assessment_weaknesses")
    op.drop_table("assessment_weaknesses")
    op.drop_index("ix_assessment_strengths_assessment_id", table_name="assessment_strengths")
    op.drop_table("assessment_strengths")
    op.drop_index("ix_assessment_component_scores_assessment_id", table_name="assessment_component_scores")
    op.drop_table("assessment_component_scores")
    op.drop_index("ix_consolidated_assessments_job_version_id", table_name="consolidated_assessments")
    op.drop_table("consolidated_assessments")
