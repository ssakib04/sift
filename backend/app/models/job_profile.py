"""Locked job profile persisted for candidate screening."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field

from app.models.base import ValidatedSQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobProfile(ValidatedSQLModel, table=True):
    """Recruiter-defined job used as the scoring source for candidates."""

    __tablename__ = "job_profile"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, sa_type=Text)
    requirements: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column_kwargs={"onupdate": _utcnow},
    )
