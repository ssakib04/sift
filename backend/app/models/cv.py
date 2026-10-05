"""Parsed curriculum vitae and its embedding."""

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from pydantic import field_validator
from sqlalchemy import JSON, Column, Text
from sqlmodel import Field

from app.models.base import ValidatedSQLModel

EMBEDDING_DIMENSIONS = 384


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CV(ValidatedSQLModel, table=True):
    """Stored CV file, extracted text, and vector representation."""

    __tablename__ = "cv"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    candidate_id: uuid.UUID = Field(foreign_key="candidate.id", index=True)
    file_hash: str = Field(unique=True, index=True)
    file_name: str
    file_size: int
    mime_type: str
    file_path: str = Field(min_length=1, max_length=1024)
    character_count: int = Field(default=0)
    extraction_status: str = Field(default="completed", index=True)
    raw_text: str = Field(min_length=1, sa_type=Text)
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(
            Vector(EMBEDDING_DIMENSIONS).with_variant(JSON(), "sqlite"),
            nullable=True,
        ),
    )
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("embedding")
    @classmethod
    def _validate_embedding_dimensions(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and len(value) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"embedding must contain {EMBEDDING_DIMENSIONS} floats")
        return value
