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
    processing_status: str = ""


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
    is_final: bool = True


class PracticeSessionRead(OpenedSessionRead):
    guest_url: str


class CopilotRead(BaseModel):
    explored: list[str]
    gaps: list[str]
    suggested_question: str
    profile_available: bool = True


class CopilotAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class CopilotAskRead(BaseModel):
    reply: str
    questions: list[str]
    profile_available: bool


class QAPairRead(BaseModel):
    pair_id: str
    question: str
    answer: str
    intent: str
    citation: str
    query_ids: list[str]
    relevance: float
    technical_accuracy: float
    completeness: float
    articulation: float


class JustificationRead(BaseModel):
    claim: str
    citation: str


class AnalysisRead(BaseModel):
    relevance: float
    technical_accuracy: float
    completeness: float
    articulation: float
    gaps: list[str]
    discrepancies: list[str]
    summary: str
    justifications: list[JustificationRead]
    pairs: list[QAPairRead]
    llm_tier: str
    fallback_used: bool
