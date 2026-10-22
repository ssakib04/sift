from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.job import JobRead

CopilotRole = Literal["user", "assistant"]
CopilotAction = Literal[
    "reply",
    "create_job",
    "list_jobs",
    "list_policies",
    "rank_job",
    "open_candidate",
    "explain_rank",
    "pipeline",
    "open_job",
    "open_report",
    "navigate",
    "start_practice",
    "offer_approve",
    "offer_inbox",
]
CopilotChipKind = Literal["navigate", "prompt", "report", "confirm"]
CopilotConfirm = Literal["", "approve", "inbox"]
CopilotFocus = Literal["stuck", "empty", "summary"]


class CopilotMessage(BaseModel):
    role: CopilotRole
    content: str = Field(min_length=1, max_length=4000)


class CopilotTurnRequest(BaseModel):
    messages: list[CopilotMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def latest_message_is_from_recruiter(self) -> "CopilotTurnRequest":
        if self.messages[-1].role != "user":
            raise ValueError("the latest message must be from the recruiter")
        return self


class CopilotPlan(BaseModel):
    action: CopilotAction
    message: str = ""
    job: dict[str, object] | None = None
    job_query: str = ""
    candidate_name: str = ""
    other_name: str = ""
    focus: CopilotFocus = "summary"
    place: str = ""


class CopilotNavigation(BaseModel):
    href: str
    label: str = ""


class CopilotChip(BaseModel):
    label: str
    kind: CopilotChipKind
    href: str = ""
    prompt: str = ""
    candidate_id: UUID | None = None
    confirm: CopilotConfirm = ""
    job_id: UUID | None = None
    version_number: int | None = None


class CopilotPractice(BaseModel):
    session_id: UUID
    token: str
    role: str
    guest_url: str


class CopilotTurnResponse(BaseModel):
    message: str
    job: JobRead | None = None
    navigation: CopilotNavigation | None = None
    chips: list[CopilotChip] = Field(default_factory=list)
    report_candidate_id: UUID | None = None
    practice: CopilotPractice | None = None
