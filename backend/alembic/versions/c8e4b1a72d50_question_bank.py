"""company question bank uploaded beside policies

Revision ID: c8e4b1a72d50
Revises: b6d2f8a41c90
Create Date: 2026-10-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e4b1a72d50"
down_revision: str | None = "b6d2f8a41c90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "question_bank_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=127), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "question_bank_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["question_bank_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_question_bank_questions_document_id", "question_bank_questions", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_question_bank_questions_document_id", table_name="question_bank_questions")
    op.drop_table("question_bank_questions")
    op.drop_table("question_bank_documents")
