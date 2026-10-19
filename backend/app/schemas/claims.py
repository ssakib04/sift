from uuid import UUID

from pydantic import BaseModel, Field


class ClaimFlagRead(BaseModel):
    claim_id: str
    kind: str
    statement: str
    status: str
    cv_quote: str
    interview_quote: str
    follow_up: str


class ClaimVerificationRead(BaseModel):
    candidate_id: UUID
    llm_tier: str
    fallback_used: bool
    supported_count: int = 0
    flags: list[ClaimFlagRead] = Field(default_factory=list)
