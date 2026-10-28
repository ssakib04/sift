import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.question_bank import QuestionBankDocument, QuestionBankQuestion
from app.services.documents import EmptyDocumentError, extract_text

_STOP = frozenset(
    """
    a an the of to and or for in on with your you how what why when where who
    do does did is are was were can have has had please tell describe explain
    me my we our about from that this into
    """.split()
)


def parse_question_bank(text: str) -> list[str]:
    """Pull interview questions out of a policy-style document."""
    cleaned = " ".join(text.split())
    pieces = re.split(r"(?<=\?)\s+|\s+(?=\d+[\).\]]\s+)", cleaned)
    questions: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        line = re.sub(r"^\d+[\).\]]\s*", "", piece).strip(" -*")
        if len(line) < 12:
            continue
        if not line.endswith("?"):
            if not re.match(r"^(how|what|why|when|where|who|describe|tell|explain|can|have|do)\b", line, re.I):
                continue
            line = line.rstrip(".") + "?"
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        questions.append(line)
    return questions


def related_bank_questions(topic: str, bank: list[str], *, limit: int = 5) -> list[str]:
    """Bank questions that share the topic. An unrelated bank returns nothing."""
    topic_terms = _terms(topic)
    if not topic_terms:
        return []
    scored: list[tuple[int, str]] = []
    for question in bank:
        overlap = _overlap(topic_terms, _terms(question))
        if not overlap:
            continue
        long = any(len(word) >= 5 for word in overlap)
        if not long and len(overlap) < 2:
            continue
        scored.append((len(overlap), question))
    scored.sort(key=lambda item: (-item[0], item[1].casefold()))
    return [question for _score, question in scored[:limit]]


def prefer_bank_question(written: str, topic: str, bank: list[str], transcript: str) -> str:
    """Use a related bank question as written. Otherwise keep the generated question."""
    for question in related_bank_questions(topic, bank):
        if question.casefold() not in transcript.casefold():
            return question
    return written


def spoken_with_bank(say: str, topic: str, bank: list[str], transcript: str) -> str:
    """Keep the reply, and ask a related bank question in the company's words."""
    chosen = prefer_bank_question(say, topic, bank, transcript)
    if not chosen or chosen == say or chosen.casefold() in say.casefold():
        return say
    parts = re.split(r"(?<=[.!?])\s+", say.strip())
    if parts and parts[-1].endswith("?"):
        parts[-1] = chosen
        return " ".join(parts)
    if not say.strip():
        return chosen
    return f"{say.rstrip()} {chosen}"


def prefer_bank_list(written: list[str], topic: str, bank: list[str], transcript: str) -> list[str]:
    related = [
        question
        for question in related_bank_questions(topic, bank)
        if question.casefold() not in transcript.casefold()
    ]
    if not related:
        return written
    merged: list[str] = []
    for question in related + written:
        if question not in merged:
            merged.append(question)
    return merged[:5]


async def list_question_texts(session: AsyncSession) -> list[str]:
    statement = (
        select(QuestionBankQuestion.text)
        .join(QuestionBankDocument)
        .order_by(QuestionBankDocument.created_at, QuestionBankQuestion.sequence)
    )
    return list((await session.scalars(statement)).all())


async def list_question_documents(session: AsyncSession) -> list[QuestionBankDocument]:
    statement = (
        select(QuestionBankDocument)
        .options(selectinload(QuestionBankDocument.questions))
        .order_by(QuestionBankDocument.created_at.desc())
    )
    return list((await session.scalars(statement)).unique().all())


async def ingest_question_bank(
    session: AsyncSession,
    *,
    filename: str,
    media_type: str,
    data: bytes,
) -> QuestionBankDocument:
    text = extract_text(filename, data)
    questions = parse_question_bank(text)
    if not questions:
        raise EmptyDocumentError("The file did not contain any interview questions.")
    document = QuestionBankDocument(
        id=uuid.uuid4(),
        filename=filename,
        media_type=media_type,
        created_at=datetime.now(UTC),
    )
    document.questions = [
        QuestionBankQuestion(id=uuid.uuid4(), document_id=document.id, sequence=index, text=question)
        for index, question in enumerate(questions)
    ]
    session.add(document)
    await session.commit()
    return document


def _terms(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.casefold()) if word not in _STOP and len(word) > 2}


def _overlap(left: set[str], right: set[str]) -> set[str]:
    found: set[str] = set()
    for word in left:
        for other in right:
            same = word == other
            stem = len(word) >= 5 and len(other) >= 5 and (word.startswith(other) or other.startswith(word))
            if same or stem:
                found.add(word)
                break
    return found
