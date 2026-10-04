"""Shared SQLModel constructor that enforces Pydantic validation."""

from contextvars import ContextVar
from typing import Any

from sqlmodel import SQLModel

_validating: ContextVar[bool] = ContextVar("sift_model_validating", default=False)


class ValidatedSQLModel(SQLModel):
    """Table model base that runs field validation when a row is constructed."""

    def __init__(self, **data: Any) -> None:
        if not _validating.get():
            token = _validating.set(True)
            try:
                type(self).model_validate(data)
            finally:
                _validating.reset(token)
        super().__init__(**data)
