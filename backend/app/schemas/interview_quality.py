from uuid import UUID

from pydantic import BaseModel, Field


class QualityDimensionRead(BaseModel):
    key: str
    label: str
    score: float | None
    note: str


class QualityRecommendationRead(BaseModel):
    kind: str
    text: str


class InterviewQualityRead(BaseModel):
    candidate_id: UUID
    overall_score: float
    summary: str
    interviewer_share: float
    candidate_share: float
    dimensions: list[QualityDimensionRead] = Field(default_factory=list)
    recommendations: list[QualityRecommendationRead] = Field(default_factory=list)
