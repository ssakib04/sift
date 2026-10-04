"""Interview session linking a candidate to a job profile."""

import uuid
from datetime import datetime

from pydantic import field_validator
from sqlmodel import Field

from app.models.base import ValidatedSQLModel

_SESSION_STATUSES = frozenset({"scheduled", "in_progress", "completed"})


class Session(ValidatedSQLModel, table=True):
    """Lifecycle record for a scheduled or completed interview."""

    __tablename__ = "session"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    candidate_id: uuid.UUID = Field(foreign_key="candidate.id", index=True)
    job_profile_id: uuid.UUID = Field(foreign_key="job_profile.id", index=True)
    status: str = Field(min_length=1, max_length=32)
    started_at: datetime | None = Field(default=None)
    ended_at: datetime | None = Field(default=None)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in _SESSION_STATUSES:
            raise ValueError("status must be scheduled, in_progress, or completed")
        return value
