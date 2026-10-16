from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.job import QUERY_IDS

QuizStatus = Literal["in_progress", "submitted"]
RecruiterQuizStatus = Literal["not_started", "in_progress", "submitted"]


class QuizQuestion(BaseModel):
    question_id: str
    query_id: str
    prompt: str = Field(min_length=8)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=8)

    @field_validator("question_id", "query_id")
    @classmethod
    def known_id(cls, value: str) -> str:
        if value not in QUERY_IDS:
            raise ValueError("question ids must be Q1 through Q10")
        return value

    @field_validator("prompt", "explanation")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 8:
            raise ValueError("text must be at least 8 characters")
        return cleaned

    @field_validator("options")
    @classmethod
    def distinct_options(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("every option must contain text")
        if len({item.casefold() for item in cleaned}) != 4:
            raise ValueError("the four options must be different")
        return cleaned


class QuizPaper(BaseModel):
    questions: list[QuizQuestion]

    @model_validator(mode="after")
    def one_question_per_checklist_query(self) -> "QuizPaper":
        by_id = {question.question_id: question for question in self.questions}
        if set(by_id) != set(QUERY_IDS) or len(self.questions) != len(QUERY_IDS):
            raise ValueError("The quiz must contain Q1 through Q10 once each.")
        ordered: list[QuizQuestion] = []
        for query_id in QUERY_IDS:
            question = by_id[query_id]
            if question.query_id != query_id:
                raise ValueError("Each question must cite the same checklist query.")
            ordered.append(question)
        self.questions = ordered
        return self


class QuizSubmitRequest(BaseModel):
    answers: list[int | None]

    @field_validator("answers")
    @classmethod
    def ten_option_indexes(cls, value: list[int | None]) -> list[int | None]:
        if len(value) != 10:
            raise ValueError("Submit one choice for each of the 10 questions.")
        for item in value:
            if item is not None and item not in {0, 1, 2, 3}:
                raise ValueError("Each answer must be an option from 0 to 3.")
        return value


class CandidateQuestionRead(BaseModel):
    question_id: str
    prompt: str
    options: list[str]


class QuestionReviewRead(BaseModel):
    question_id: str
    prompt: str
    options: list[str]
    selected_index: int | None
    correct_index: int
    explanation: str
    correct: bool


class CandidateQuizRead(BaseModel):
    status: QuizStatus
    seconds_remaining: int = Field(ge=0)
    time_limit_seconds: int = Field(gt=0)
    questions: list[CandidateQuestionRead]
    review: list[QuestionReviewRead] | None = None


class RecruiterQuizRead(BaseModel):
    candidate_id: UUID
    status: RecruiterQuizStatus
    score: int | None = Field(default=None, ge=0, le=100)
    correct_count: int | None = Field(default=None, ge=0, le=10)
    time_limit_seconds: int | None = None
    submitted_at: datetime | None = None
    review: list[QuestionReviewRead] = Field(default_factory=list)
