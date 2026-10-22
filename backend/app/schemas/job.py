from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

Seniority = Literal["Junior", "Mid-Level", "Senior", "Not specified"]
Contract = Literal["Full Time", "Part Time", "Freelance", "Internship"]
Dimension = Literal["technical", "experience", "qualification"]
RequirementType = Literal["must_have", "preferred"]

JOB_CATEGORIES: frozenset[str] = frozenset(
    {
        "Accounting",
        "Administrative",
        "Arts and Design",
        "Community & Social Services",
        "Consulting",
        "Education",
        "Engineering",
        "Entrepreneurship",
        "Finance",
        "Healthcare Services",
        "Human Resources",
        "Information Technology",
        "Legal",
        "Marketing",
        "Media & Communications",
        "Military & Protective Services",
        "Operations",
        "Program & Product Management",
        "Purchasing",
        "Quality Assurance",
        "Real Estate",
        "Research",
        "Sales",
        "Support",
        "None",
    }
)
QUERY_IDS: tuple[str, ...] = tuple(f"Q{index}" for index in range(1, 11))


class ChecklistQuery(BaseModel):
    query_id: str
    question: str = Field(min_length=8)
    dimension: Dimension
    requirement_type: RequirementType
    weight: float = Field(ge=0)
    evidence_hints: list[str] = Field(min_length=1)
    scoring_rubric: str = Field(min_length=8)

    @field_validator("scoring_rubric", mode="before")
    @classmethod
    def rubric_as_text(cls, value: object) -> object:
        if isinstance(value, dict):
            parts = [str(item).strip() for item in value.values() if str(item).strip()]
            return " ".join(parts)
        if isinstance(value, list):
            return " ".join(str(item).strip() for item in value if str(item).strip())
        return value

    @field_validator("evidence_hints", mode="before")
    @classmethod
    def hints_as_list(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("query_id")
    @classmethod
    def known_query_id(cls, value: str) -> str:
        if value not in QUERY_IDS:
            raise ValueError("query_id must be Q1 through Q10")
        return value


class ChecklistQuerySet(BaseModel):
    queries: list[ChecklistQuery]

    @model_validator(mode="after")
    def exactly_ten_unique_queries(self) -> "ChecklistQuerySet":
        identifiers = [query.query_id for query in self.queries]
        if set(identifiers) != set(QUERY_IDS):
            raise ValueError("checklist must contain each query id from Q1 through Q10 once")
        ordered = sorted(self.queries, key=lambda query: int(query.query_id[1:]))
        weights = [query.weight if query.weight > 0 else 0.0 for query in ordered]
        if sum(weights) <= 0:
            weights = [1 / len(ordered)] * len(ordered)
        else:
            floor = min(weight for weight in weights if weight > 0)
            weights = [weight if weight > 0 else floor for weight in weights]
            total = sum(weights)
            weights = [weight / total for weight in weights]
        self.queries = [
            query.model_copy(update={"weight": weight}) for query, weight in zip(ordered, weights, strict=True)
        ]
        return self


class JobCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    seniority: Seniority
    required_skills: list[str] = Field(min_length=1)
    preferred_skills: list[str] = Field(default_factory=list)
    qualifications: str = Field(min_length=2)
    minimum_years: int = Field(ge=0, le=50)
    technical_weight: float = Field(default=0.5, ge=0, le=1)
    experience_weight: float = Field(default=0.3, ge=0, le=1)
    qualification_weight: float = Field(default=0.2, ge=0, le=1)
    contract: Contract = "Full Time"
    category: str = "Information Technology"

    @field_validator("required_skills", "preferred_skills")
    @classmethod
    def strip_skills(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        if value not in JOB_CATEGORIES:
            raise ValueError("category is not a supported job board category")
        return value

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "JobCreateRequest":
        total = self.technical_weight + self.experience_weight + self.qualification_weight
        if abs(total - 1.0) > 0.001:
            raise ValueError("dimension weights must sum to 1")
        if not self.required_skills:
            raise ValueError("at least one required skill is needed")
        return self


class JobVersionUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=100)
    queries: list[ChecklistQuery] | None = None

    @model_validator(mode="after")
    def normalize_queries(self) -> "JobVersionUpdate":
        if self.queries is not None:
            self.queries = ChecklistQuerySet(queries=self.queries).queries
        return self


class ChecklistQueryRead(BaseModel):
    query_id: str
    question: str
    dimension: str
    requirement_type: str
    weight: float
    evidence_hints: list[str]
    scoring_rubric: str


class JobVersionRead(BaseModel):
    id: UUID
    version_number: int
    status: str
    seniority: str
    required_skills: list[str]
    preferred_skills: list[str]
    qualifications: str
    minimum_years: int
    technical_weight: float
    experience_weight: float
    qualification_weight: float
    contract: str
    category: str
    description: str
    queries: list[ChecklistQueryRead]
    llm_tier: str
    fallback_used: bool
    created_at: datetime
    locked_at: datetime | None
    posting_status: str | None
    posting_detail: str | None
    external_posting_id: str | None
    apply_url: str | None


class JobRead(BaseModel):
    id: UUID
    title: str
    mail_subject: str
    apply_email: str
    created_at: datetime
    versions: list[JobVersionRead]
