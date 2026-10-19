from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ProgressStage = Literal["received", "screened", "invited", "interview", "quiz", "assessed"]


class ProgressCardRead(BaseModel):
    candidate_id: UUID
    full_name: str
    rank: int | None = None
    detail: str = ""
    interview_status: str = ""


class ProgressColumnRead(BaseModel):
    stage: ProgressStage
    label: str
    cards: list[ProgressCardRead] = Field(default_factory=list)


class ProgressBoardRead(BaseModel):
    job_id: UUID
    job_title: str
    applicant_count: int = Field(ge=0)
    columns: list[ProgressColumnRead]
