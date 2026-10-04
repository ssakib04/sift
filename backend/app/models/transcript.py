"""Timestamped interview transcript turn."""

import uuid

from pydantic import field_validator
from sqlalchemy import Text
from sqlmodel import Field

from app.models.base import ValidatedSQLModel

_SPEAKERS = frozenset({"interviewer", "candidate"})


class Transcript(ValidatedSQLModel, table=True):
    """One spoken turn captured during an interview session."""

    __tablename__ = "transcript"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(foreign_key="session.id", index=True)
    speaker: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, sa_type=Text)
    timestamp_ms: int = Field(ge=0)

    @field_validator("speaker")
    @classmethod
    def _validate_speaker(cls, value: str) -> str:
        if value not in _SPEAKERS:
            raise ValueError("speaker must be interviewer or candidate")
        return value
