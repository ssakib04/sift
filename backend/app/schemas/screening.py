from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class QueryEvaluationRead(BaseModel):
    query_id: str
    status: str
    confidence: float
    evidence: str
    semantic_score: float


class CandidateRead(BaseModel):
    id: UUID
    email: str
    full_name: str
    rank: int | None
    aggregate_score: float | None
    must_have_ratio: float | None
    parse_status: str
    parse_method: str
    invited: bool
    fairness_flags: list[str]
    justifications: list[str]
    evaluations: list[QueryEvaluationRead]


class InboxPollRead(BaseModel):
    processed: int = Field(ge=0)


class InviteRead(BaseModel):
    job_title: str
    company_name: str
    status: str
    created_at: datetime
