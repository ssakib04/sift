from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class QuestionBankDocumentRead(BaseModel):
    id: UUID
    filename: str
    media_type: str
    created_at: datetime
    question_count: int = Field(ge=0)
