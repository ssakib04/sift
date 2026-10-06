from typing import TypedDict

from app.schemas.job import ChecklistQuery


class CVScreeningState(TypedDict, total=False):
    filename: str
    file_bytes: bytes
    job_description: str
    locked_checklist: list[dict[str, object]]
    parse_method: str
    parse_confidence: float
    warnings: list[str]
    raw_text: str
    extracted_attributes: dict[str, object]
    semantic_matches: list[dict[str, float | str]]
    query_evaluations: list[dict[str, object]]
    aggregate_score: float
    must_have_ratio: float
    technical_score: float
    experience_score: float
    qualification_score: float
    justifications: list[str]
    fairness_flags: list[str]
    llm_tier: str
    fallback_used: bool
    errors: list[str]


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
