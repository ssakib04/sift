from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


Suitability = Literal["strong_fit", "moderate_fit", "unsuited", "insufficient_evidence"]


class TraceLinkRead(BaseModel):
    claim: str
    source_type: str
    source_reference: str
    evidence: str


class ComponentScoresRead(BaseModel):
    cv_screening: float | None = None
    mcq_quiz: float | None = None
    interview_qa: float | None = None
    technical_dimension: float | None = None
    experience_dimension: float | None = None
    qualification_dimension: float | None = None


class AssessmentRunRead(BaseModel):
    state: Literal["started"]


class AssessmentRead(BaseModel):
    candidate_id: UUID
    full_name: str
    job_title: str
    overall_suitability: Suitability
    suitability_label: str
    overall_score: float | None
    component_scores: ComponentScoresRead
    strengths: list[str]
    weaknesses: list[str]
    evidence_gaps: list[str]
    traceability: list[TraceLinkRead]
    narrative: str
    cv_weight: float
    mcq_weight: float
    interview_weight: float
    llm_tier: str
    fallback_used: bool
    created_at: datetime
    run_state: Literal["idle", "running", "failed"] = "idle"
    run_message: str = ""


class ComparisonRowRead(BaseModel):
    candidate_id: UUID
    full_name: str
    overall_score: float | None
    overall_suitability: Suitability | None
    suitability_label: str
    technical_dimension: float | None
    experience_dimension: float | None
    qualification_dimension: float | None
    mcq_score: float | None
    interview_qa: float | None
    key_gap: str


class JobComparisonRead(BaseModel):
    job_id: UUID
    job_title: str
    cv_weight: float = Field(gt=0, lt=1)
    mcq_weight: float = Field(gt=0, lt=1)
    interview_weight: float = Field(gt=0, lt=1)
    rows: list[ComparisonRowRead]
