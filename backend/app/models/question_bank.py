import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class QuestionBankDocument(Base):
    __tablename__ = "question_bank_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(127))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    questions: Mapped[list["QuestionBankQuestion"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class QuestionBankQuestion(Base):
    __tablename__ = "question_bank_questions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("question_bank_documents.id", ondelete="CASCADE"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    document: Mapped[QuestionBankDocument] = relationship(back_populates="questions")
