"""Schemas for job-description synthesis and the locked evaluation checklist."""

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, model_validator

QueryId = Literal["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10"]
RequirementDimension = Literal["technical", "experience", "qualification"]
RequirementType = Literal["must_have", "preferred"]


class LockedChecklistQuery(BaseModel):
    """One frozen evaluation query for a job version."""

    query_id: QueryId
    question: str = Field(min_length=1)
    dimension: RequirementDimension
    requirement_type: RequirementType
    weight: float = Field(ge=0, le=1)
    evidence_hints: list[str]
    scoring_rubric: str = Field(min_length=1)


class GeneratedJobDescription(BaseModel):
    """Recruiter-facing job description produced by Workflow 1."""

    title: str = Field(min_length=1)
    seniority: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    responsibilities: list[str]
    required_skills: list[str]
    preferred_skills: list[str]
    qualification_requirements: list[str]
    minimum_years_experience: int = Field(ge=0)
    salary_range_summary: str = Field(min_length=1)
    remote_policy_summary: str = Field(min_length=1)


class DimensionalWeights(BaseModel):
    """Weight distribution across the three scoring dimensions."""

    technical: float = Field(default=0.50, ge=0, le=1)
    experience: float = Field(default=0.30, ge=0, le=1)
    qualification: float = Field(default=0.20, ge=0, le=1)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "DimensionalWeights":
        total = self.technical + self.experience + self.qualification
        if abs(total - 1.0) > 0.001:
            raise ValueError("dimensional weights must sum to 1.0")
        return self


class JobCreationState(TypedDict, total=False):
    """State carried through LangGraph Workflow 1."""

    role_title: str
    seniority_level: str
    core_skills: list[str]
    min_years_exp: int
    raw_prompt: str
    retrieved_policy_chunks: list[str]
    is_clear: bool
    clarifying_questions: list[str]
    recruiter_answers: list[str]
    synthesized_jd: dict[str, Any] | None
    dimensional_weights: dict[str, float] | None
    locked_checklist: list[dict[str, Any]]
    schema_valid: bool
    validation_errors: list[str]
    job_version_id: str
