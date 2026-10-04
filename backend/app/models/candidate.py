"""Candidate identity record."""

import re
import uuid
from datetime import datetime, timezone

from pydantic import field_validator
from sqlmodel import Field

from app.models.base import ValidatedSQLModel

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Candidate(ValidatedSQLModel, table=True):
    """Person being screened for a role."""

    __tablename__ = "candidate"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(index=True, unique=True, max_length=320)
    phone: str | None = Field(default=None, max_length=32)
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        if _EMAIL_RE.fullmatch(value) is None:
            raise ValueError("email must be a valid email address")
        return value
