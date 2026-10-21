from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PerformanceDimensionRead(BaseModel):
    key: str
    label: str
    score: float
    evidence: str
    note: str


class InterviewScoreRead(BaseModel):
    candidate_id: UUID
    overall_score: float
    summary: str
    llm_tier: str
    fallback_used: bool
    dimensions: list[PerformanceDimensionRead] = Field(default_factory=list)


class InterviewHistoryRead(BaseModel):
    session_id: UUID
    candidate_id: UUID
    full_name: str
    job_title: str
    conductor: str
    status: str
    ended_at: datetime | None
    interview_score: float | None
