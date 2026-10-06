from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.job import JobRead

CopilotRole = Literal["user", "assistant"]
CopilotAction = Literal["reply", "create_job", "list_jobs", "list_policies"]


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


class CopilotTurnResponse(BaseModel):
    message: str
    job: JobRead | None = None
