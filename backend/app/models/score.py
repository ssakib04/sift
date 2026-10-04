"""Pre-interview dimensional score snapshot."""

import uuid

from pydantic import field_validator
from sqlalchemy import JSON, Column, Text
from sqlmodel import Field

from app.models.base import ValidatedSQLModel

_DIMENSION_KEYS = frozenset({"technical", "communication", "problem-solving"})


class Score(ValidatedSQLModel, table=True):
    """Checklist scoring result for one candidate against one job profile."""

    __tablename__ = "score"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    candidate_id: uuid.UUID = Field(foreign_key="candidate.id", index=True)
    job_profile_id: uuid.UUID = Field(foreign_key="job_profile.id", index=True)
    dimensional_scores: dict[str, float] = Field(sa_column=Column(JSON, nullable=False))
    overall_score: float = Field(ge=0, le=100)
    summary: str = Field(min_length=1, sa_type=Text)

    @field_validator("dimensional_scores")
    @classmethod
    def _validate_dimensional_scores(cls, value: dict[str, float]) -> dict[str, float]:
        missing = _DIMENSION_KEYS.difference(value)
        if missing:
            missing_keys = ", ".join(sorted(missing))
            raise ValueError(f"dimensional_scores missing keys: {missing_keys}")
        return value
