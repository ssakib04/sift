"""post-call question and answer pairs

Revision ID: b2e8c4a91d60
Revises: a9c4e2b71d50
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2e8c4a91d60"
down_revision: str | None = "a9c4e2b71d50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_analyses",
        sa.Column("discrepancies", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "interview_analyses",
        sa.Column("justifications", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.create_table(
        "qa_pairs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("pair_id", sa.String(length=16), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("citation", sa.String(length=80), nullable=False),
        sa.Column("query_ids", sa.JSON(), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=False),
        sa.Column("technical_accuracy", sa.Float(), nullable=False),
        sa.Column("completeness", sa.Float(), nullable=False),
        sa.Column("articulation", sa.Float(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["interview_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "pair_id", name="uq_analysis_pair_id"),
    )
    op.create_index("ix_qa_pairs_analysis_id", "qa_pairs", ["analysis_id"])


def downgrade() -> None:
    op.drop_index("ix_qa_pairs_analysis_id", table_name="qa_pairs")
    op.drop_table("qa_pairs")
    op.drop_column("interview_analyses", "justifications")
    op.drop_column("interview_analyses", "discrepancies")
