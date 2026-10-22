from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class QueryEvaluationRead(BaseModel):
    query_id: str
    question: str = ""
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
    mcq_score: int | None = None
    must_have_ratio: float | None
    parse_status: str
    parse_method: str
    invited: bool
    has_photo: bool = False
    fairness_flags: list[str]
    justifications: list[str]
    evaluations: list[QueryEvaluationRead]
    job_id: UUID | None = None
    job_title: str = ""
    scheduled_label: str = ""
    created_at: datetime


class CandidateGroupRead(BaseModel):
    job_id: UUID
    job_title: str
    mail_subject: str
    candidates: list[CandidateRead]


class InboxPollRead(BaseModel):
    processed: int = Field(ge=0)


class CvUploadItemRead(BaseModel):
    filename: str
    outcome: str


class CvUploadRead(BaseModel):
    scored: int = Field(ge=0)
    duplicate: int = Field(ge=0)
    parse_failed: int = Field(ge=0)
    invalid: int = Field(ge=0)
    failed: int = Field(ge=0)
    items: list[CvUploadItemRead]


class InviteRead(BaseModel):
    job_title: str
    company_name: str
    status: str
    created_at: datetime
    scheduled_label: str = ""
