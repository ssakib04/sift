"""Job, version, and frozen checklist tables."""

import uuid
from datetime import datetime, timezone

from pydantic import field_validator
from sqlalchemy import JSON, Column, Text, UniqueConstraint
from sqlmodel import Field

from app.models.base import ValidatedSQLModel

_QUERY_IDS = frozenset(f"Q{index}" for index in range(1, 11))
_DIMENSIONS = frozenset({"technical", "experience", "qualification"})
_REQUIREMENT_TYPES = frozenset({"must_have", "preferred"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(ValidatedSQLModel, table=True):
    """Recruiter role that can have multiple locked requirement versions."""

    __tablename__ = "jobs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(min_length=1, max_length=200)
    seniority: str = Field(min_length=1, max_length=50)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": _utcnow},
    )


class JobVersion(ValidatedSQLModel, table=True):
    """Frozen job-description revision and its dimensional weights."""

    __tablename__ = "job_versions"
    __table_args__ = (UniqueConstraint("job_id", "version_number"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_id: uuid.UUID = Field(foreign_key="jobs.id", index=True)
    version_number: int = Field(ge=1)
    synthesized_jd: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    dimensional_weights: dict[str, float] = Field(sa_column=Column(JSON, nullable=False))
    is_frozen: bool = Field(default=True)
    schema_valid: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)


class JobChecklistQuery(ValidatedSQLModel, table=True):
    """One of the ten frozen evaluation queries for a job version."""

    __tablename__ = "job_checklist_queries"
    __table_args__ = (UniqueConstraint("job_version_id", "query_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    job_version_id: uuid.UUID = Field(foreign_key="job_versions.id", index=True)
    query_id: str = Field(min_length=2, max_length=3)
    question: str = Field(min_length=1, sa_type=Text)
    dimension: str = Field(min_length=1, max_length=32)
    requirement_type: str = Field(min_length=1, max_length=32)
    weight: float = Field(ge=0, le=1)
    evidence_hints: list[str] = Field(sa_column=Column(JSON, nullable=False))
    scoring_rubric: str = Field(min_length=1, sa_type=Text)

    @field_validator("query_id")
    @classmethod
    def _validate_query_id(cls, value: str) -> str:
        if value not in _QUERY_IDS:
            raise ValueError("query_id must be Q1 through Q10")
        return value

    @field_validator("dimension")
    @classmethod
    def _validate_dimension(cls, value: str) -> str:
        if value not in _DIMENSIONS:
            raise ValueError("dimension must be technical, experience, or qualification")
        return value

    @field_validator("requirement_type")
    @classmethod
    def _validate_requirement_type(cls, value: str) -> str:
        if value not in _REQUIREMENT_TYPES:
            raise ValueError("requirement_type must be must_have or preferred")
        return value
