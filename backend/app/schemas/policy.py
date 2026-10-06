from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PolicyDocumentRead(BaseModel):
    id: UUID
    filename: str
    media_type: str
    created_at: datetime
    chunk_count: int
