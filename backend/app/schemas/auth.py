from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class LoginRead(BaseModel):
    token: str
    role: str


class RecruiterRead(BaseModel):
    role: str
