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
    biometric_consent: bool = False


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
    biometric_consented_at: datetime | None = None
    conductor: str = ""


class ProfileOverviewRead(BaseModel):
    candidate_id: UUID
    full_name: str
    headline: str
    skills: list[str]
    pre_interview_score: float | None
    probe_areas: list[str]


class IdentificationFrameRequest(BaseModel):
    image_base64: str = Field(min_length=32, max_length=2_000_000)


class IdentificationAck(BaseModel):
    status: str
    concluded: bool = False
    sample_count: int = 0
    sample_limit: int = 8


class IdentificationRead(BaseModel):
    status: str
    message: str
    similarity: float | None = None
    invited_similarity: float | None = None
    invited_name: str
    matched_name: str | None = None
    hint_name: str | None = None
    profile: ProfileOverviewRead | None = None
    concluded: bool = False
    sample_count: int = 0
    sample_limit: int = 8


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
