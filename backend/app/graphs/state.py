from typing import TypedDict

from app.schemas.job import ChecklistQuery


class JobCreationState(TypedDict, total=False):
    title: str
    seniority: str
    required_skills: list[str]
    preferred_skills: list[str]
    qualifications: str
    minimum_years: int
    technical_weight: float
    experience_weight: float
    qualification_weight: float
    policy_excerpts: list[str]
    description: str
    queries: list[ChecklistQuery]
    llm_tier: str
    fallback_used: bool
