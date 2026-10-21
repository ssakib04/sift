from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ApplicantNoticeRead(BaseModel):
    id: UUID
    candidate_id: UUID
    full_name: str
    job_title: str
    rank: int | None
    message: str
    created_at: datetime
    read: bool


class ApplicantNoticeListRead(BaseModel):
    unread_count: int = Field(ge=0)
    notices: list[ApplicantNoticeRead]
