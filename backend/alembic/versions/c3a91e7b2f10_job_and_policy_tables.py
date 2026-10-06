"""job and policy tables

Revision ID: c3a91e7b2f10
Revises: b7e1c4a2d901
Create Date: 2026-10-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "c3a91e7b2f10"
down_revision: str | None = "b7e1c4a2d901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=127), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "policy_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["policy_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_policy_chunks_document_id", "policy_chunks", ["document_id"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "job_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("seniority", sa.String(length=32), nullable=False),
        sa.Column("required_skills", sa.JSON(), nullable=False),
        sa.Column("preferred_skills", sa.JSON(), nullable=False),
        sa.Column("qualifications", sa.Text(), nullable=False),
        sa.Column("minimum_years", sa.Integer(), nullable=False),
        sa.Column("technical_weight", sa.Float(), nullable=False),
        sa.Column("experience_weight", sa.Float(), nullable=False),
        sa.Column("qualification_weight", sa.Float(), nullable=False),
        sa.Column("contract", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("policy_excerpts", sa.JSON(), nullable=False),
        sa.Column("llm_tier", sa.String(length=32), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "version_number", name="uq_job_version_number"),
    )
    op.create_index("ix_job_versions_job_id", "job_versions", ["job_id"])
    op.create_index("ix_job_versions_status", "job_versions", ["status"])
    op.create_table(
        "job_checklist_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("query_id", sa.String(length=8), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("requirement_type", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("evidence_hints", sa.JSON(), nullable=False),
        sa.Column("scoring_rubric", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["job_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "query_id", name="uq_version_query_id"),
    )
    op.create_index("ix_job_checklist_queries_version_id", "job_checklist_queries", ["version_id"])
    op.create_table(
        "job_postings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("apply_url", sa.String(length=512), nullable=False),
        sa.Column("detail", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["version_id"], ["job_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id"),
    )


def downgrade() -> None:
    op.drop_table("job_postings")
    op.drop_table("job_checklist_queries")
    op.drop_table("job_versions")
    op.drop_table("jobs")
    op.drop_table("policy_chunks")
    op.drop_table("policy_documents")
