from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PolicyDocumentRead(BaseModel):
    id: UUID
    filename: str
    media_type: str
    created_at: datetime
    chunk_count: int


class PolicySummaryRead(BaseModel):
    id: UUID
    summary: str = Field(min_length=1, max_length=480)
