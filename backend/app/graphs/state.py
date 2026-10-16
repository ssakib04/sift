import operator
from typing import Annotated, TypedDict

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


class QAAnalysisState(TypedDict, total=False):
    turns: list[dict[str, object]]
    checklist: list[dict[str, str]]
    pairs: list[dict[str, object]]
    relevance_by_pair: dict[str, dict[str, object]]
    technical_accuracy_by_pair: dict[str, dict[str, object]]
    completeness_by_pair: dict[str, dict[str, object]]
    articulation_by_pair: dict[str, dict[str, object]]
    relevance: float
    technical_accuracy: float
    completeness: float
    articulation: float
    gaps: list[str]
    discrepancies: list[str]
    summary: str
    justifications: list[dict[str, str]]
    llm_tier: str
    fallback_used: bool
    tier_notes: Annotated[list[str], operator.add]
    fallback_flags: Annotated[list[bool], operator.add]


class MasterAssessmentState(TypedDict, total=False):
    candidate_id: str
    cv_screening: dict[str, object] | None
    mcq_score: int | None
    qa_analysis: dict[str, object] | None
    component_scores: dict[str, float | None]
    strengths: list[str]
    weaknesses: list[str]
    evidence_gaps: list[str]
    overall_score: float | None
    overall_suitability: str
    traceability: list[dict[str, str]]
    narrative: str
    llm_tier: str
    fallback_used: bool
    tier_notes: Annotated[list[str], operator.add]
    fallback_flags: Annotated[list[bool], operator.add]
