from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class FinalRankRead(BaseModel):
    candidate_id: UUID
    full_name: str
    email: str
    rank: int
    overall_score: float
    suitability_label: str
    cv_score: float | None
    interview_score: float | None
    quiz_score: int | None
    approval_mailed_at: datetime | None


class FinalRankingRead(BaseModel):
    job_id: UUID
    job_title: str
    rows: list[FinalRankRead]


class ApprovalRequest(BaseModel):
    count: int = Field(ge=1, le=500)


class ApprovalSkipRead(BaseModel):
    candidate_id: UUID
    full_name: str
    reason: str


class ApprovalBatchRead(BaseModel):
    mailed: list[FinalRankRead]
    skipped: list[ApprovalSkipRead]
