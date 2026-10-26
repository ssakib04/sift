from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ScheduledInterviewRead(BaseModel):
    session_id: UUID
    candidate_id: UUID
    full_name: str
    status: str
    schedule_label: str
    scheduled_start: datetime


class RoleInterviewsRead(BaseModel):
    job_id: UUID
    job_title: str
    interviews: list[ScheduledInterviewRead] = Field(default_factory=list)
