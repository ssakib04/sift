from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class IceServerRead(BaseModel):
    urls: str
    username: str = ""
    credential: str = ""


class CandidateOpenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)


class RecruiterOpenRequest(BaseModel):
    candidate_id: UUID


class StartInterviewRequest(BaseModel):
    consent: bool


class OpenedSessionRead(BaseModel):
    session_id: UUID
    token: str
    role: str
    status: str
    job_title: str
    company_name: str
    ice_servers: list[IceServerRead]
    livekit_url: str
    livekit_token: str


class SessionDetailRead(BaseModel):
    session_id: UUID
    role: str
    status: str
    job_title: str
    company_name: str
    ice_servers: list[IceServerRead]
    livekit_url: str
    livekit_token: str
    consented_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None


class SessionStatusRead(BaseModel):
    session_id: UUID
    status: str
    consented_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None


class TranscriptTurnRead(BaseModel):
    id: UUID
    speaker: str
    start_time: float
    end_time: float
    text: str
    confidence: float


class CopilotRead(BaseModel):
    explored: list[str]
    gaps: list[str]
    suggested_question: str


class AnalysisRead(BaseModel):
    relevance: float
    technical_accuracy: float
    completeness: float
    articulation: float
    gaps: list[str]
    summary: str
    llm_tier: str
    fallback_used: bool
