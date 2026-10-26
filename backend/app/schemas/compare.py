from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CompareRequest(BaseModel):
    left_id: UUID
    right_id: UUID


class CompareSide(BaseModel):
    candidate_id: UUID
    full_name: str
    rank: int | None
    cv_score: float | None
    technical_score: float | None
    experience_score: float | None
    qualification_score: float | None
    mcq_score: int | None
    interview_score: float | None
    interview_note: str
    overall_score: float | None
    suitability_label: str
    strengths: list[str]
    gaps: list[str]


class CandidateCompareRead(BaseModel):
    job_id: UUID
    job_title: str
    left: CompareSide
    right: CompareSide
    summary: str
    left_edge: str
    right_edge: str
    tradeoff: str
    source: Literal["model", "scores"]


class CompareNarrative(BaseModel):
    summary: str = Field(min_length=1, max_length=800)
    left_edge: str = Field(min_length=1, max_length=800)
    right_edge: str = Field(min_length=1, max_length=800)
    tradeoff: str = Field(min_length=1, max_length=800)
    source: Literal["model", "scores"]
