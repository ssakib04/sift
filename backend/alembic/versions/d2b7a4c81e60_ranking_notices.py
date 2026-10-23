"""ranking notices can point at a job without a single applicant

Revision ID: d2b7a4c81e60
Revises: c5d9e2b14a30
Create Date: 2026-10-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2b7a4c81e60"
down_revision: str | None = "c5d9e2b14a30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("applicant_notifications", "candidate_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("applicant_notifications", sa.Column("job_id", sa.Uuid(), nullable=True))
    op.add_column(
        "applicant_notifications",
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
    )
    op.create_foreign_key(
        "fk_applicant_notifications_job_id",
        "applicant_notifications",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_applicant_notifications_job_id", "applicant_notifications", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_applicant_notifications_job_id", table_name="applicant_notifications")
    op.drop_constraint("fk_applicant_notifications_job_id", "applicant_notifications", type_="foreignkey")
    op.drop_column("applicant_notifications", "summary")
    op.drop_column("applicant_notifications", "job_id")
    op.alter_column("applicant_notifications", "candidate_id", existing_type=sa.Uuid(), nullable=False)
