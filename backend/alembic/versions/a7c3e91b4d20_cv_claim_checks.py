"""cv claims checked against the interview transcript

Revision ID: a7c3e91b4d20
Revises: e8b2c4d71a50
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e91b4d20"
down_revision: str | None = "e8b2c4d71a50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cv_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("cv_quote", sa.Text(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", "claim_id", name="uq_candidate_claim"),
    )
    op.create_index("ix_cv_claims_candidate_id", "cv_claims", ["candidate_id"])
    op.create_table(
        "claim_verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("llm_tier", sa.String(length=32), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_table(
        "claim_flags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("verification_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cv_quote", sa.Text(), nullable=False),
        sa.Column("interview_quote", sa.Text(), nullable=False),
        sa.Column("follow_up", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["verification_id"], ["claim_verifications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("verification_id", "claim_id", name="uq_verification_claim"),
    )
    op.create_index("ix_claim_flags_verification_id", "claim_flags", ["verification_id"])


def downgrade() -> None:
    op.drop_index("ix_claim_flags_verification_id", table_name="claim_flags")
    op.drop_table("claim_flags")
    op.drop_table("claim_verifications")
    op.drop_index("ix_cv_claims_candidate_id", table_name="cv_claims")
    op.drop_table("cv_claims")
