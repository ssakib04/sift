"""Consolidated post-interview assessment."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.models.base import ValidatedSQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Assessment(ValidatedSQLModel, table=True):
    """Final report synthesized for one interview session."""

    __tablename__ = "assessment"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(foreign_key="session.id", index=True)
    consolidated_report: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=_utcnow)
