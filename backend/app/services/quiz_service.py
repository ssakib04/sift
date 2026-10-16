import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.llm_fallback import FallbackLLMManager, LLMFallbackExhaustedError
from app.core.session_tokens import SessionClaims
from app.models.candidate import Candidate, InterviewSession, McqAttempt
from app.models.job import JobChecklistQuery, JobVersion
from app.schemas.quiz import CandidateQuizRead, QuizPaper, QuizSubmitRequest, RecruiterQuizRead
from app.services.quiz_rules import (
    QUIZ_TIME_LIMIT_SECONDS,
    AttemptState,
    QuizGenerationError,
    QUIZ_SYSTEM,
    accept_answers,
    build_quiz_prompt,
    candidate_quiz_read,
    open_attempt,
    parse_quiz_paper,
    recruiter_quiz_read,
    settle,
)

logger = logging.getLogger(__name__)


class QuizError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def generate_quiz(
    llm: FallbackLLMManager,
    *,
    job_title: str,
    checklist: list[dict[str, str]],
    cv_text: str,
) -> tuple[AttemptState, str, bool]:
    """Ask the fallback manager for one locked-checklist quiz and start its timer."""
    prompt = build_quiz_prompt(job_title=job_title, checklist=checklist, cv_text=cv_text)
    response = await llm.complete(prompt, system=QUIZ_SYSTEM)
    paper = parse_quiz_paper(response.content)
    now = datetime.now(UTC)
    return open_attempt(paper, now, limit=QUIZ_TIME_LIMIT_SECONDS), response.tier.value, response.fallback_used


async def open_candidate_quiz(
    db: AsyncSession,
    llm: FallbackLLMManager,
    claims: SessionClaims,
    session_id: uuid.UUID,
) -> CandidateQuizRead:
    row = await _candidate_session(db, claims, session_id)
    attempt = await _ensure_attempt(db, llm, row)
    return await _candidate_view(db, attempt)


async def read_candidate_quiz(
    db: AsyncSession,
    claims: SessionClaims,
    session_id: uuid.UUID,
) -> CandidateQuizRead:
    row = await _candidate_session(db, claims, session_id)
    attempt = row.candidate.quiz_attempt if row.candidate is not None else None
    if attempt is None:
        raise QuizError("QUIZ_NOT_STARTED", "Start the skill quiz before opening it.", 404)
    return await _candidate_view(db, attempt)


async def submit_candidate_quiz(
    db: AsyncSession,
    claims: SessionClaims,
    session_id: uuid.UUID,
    body: QuizSubmitRequest,
) -> CandidateQuizRead:
    row = await _candidate_session(db, claims, session_id)
    attempt = row.candidate.quiz_attempt if row.candidate is not None else None
    if attempt is None:
        raise QuizError("QUIZ_NOT_STARTED", "Start the skill quiz before submitting it.", 404)
    now = datetime.now(UTC)
    state = settle(_state(attempt), now)
    state = accept_answers(state, tuple(body.answers), now)
    _apply(attempt, state)
    await db.commit()
    return candidate_quiz_read(state, now)


async def read_recruiter_quiz(db: AsyncSession, candidate_id: uuid.UUID) -> RecruiterQuizRead:
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).options(selectinload(Candidate.quiz_attempt))
    )
    if candidate is None:
        raise QuizError("CANDIDATE_NOT_FOUND", "Candidate not found.", 404)
    attempt = candidate.quiz_attempt
    if attempt is None:
        return recruiter_quiz_read(candidate_id, None, datetime.now(UTC))
    now = datetime.now(UTC)
    state = settle(_state(attempt), now)
    if state.submitted_at != attempt.submitted_at:
        _apply(attempt, state)
        await db.commit()
    return recruiter_quiz_read(candidate_id, state, now)


async def _candidate_view(db: AsyncSession, attempt: McqAttempt) -> CandidateQuizRead:
    now = datetime.now(UTC)
    state = settle(_state(attempt), now)
    if state.submitted_at != attempt.submitted_at:
        _apply(attempt, state)
        await db.commit()
    return candidate_quiz_read(state, now)


async def _ensure_attempt(db: AsyncSession, llm: FallbackLLMManager, row: InterviewSession) -> McqAttempt:
    candidate = row.candidate
    if candidate is None or candidate.version is None or candidate.version.job is None:
        raise QuizError("SESSION_NOT_FOUND", "This interview session is not available.", 404)
    existing = candidate.quiz_attempt
    if existing is not None:
        return existing
    version = candidate.version
    queries = _locked_queries(version)
    parse = candidate.parse_result
    cv_text = parse.raw_text if parse is not None else ""
    try:
        state, tier, fallback_used = await generate_quiz(
            llm,
            job_title=version.job.title,
            checklist=_checklist(queries),
            cv_text=cv_text,
        )
    except (QuizGenerationError, LLMFallbackExhaustedError) as exc:
        logger.warning("quiz_generation_failed error_type=%s", type(exc).__name__)
        raise QuizError("QUIZ_GENERATION_FAILED", "The skill quiz could not be prepared. Try again.", 502) from exc
    attempt = McqAttempt(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        job_version_id=version.id,
        questions=[question.model_dump() for question in state.paper.questions],
        answers=None,
        correct_count=None,
        score=None,
        time_limit_seconds=state.time_limit_seconds,
        llm_tier=tier,
        fallback_used=fallback_used,
        created_at=state.started_at,
        started_at=state.started_at,
        submitted_at=None,
    )
    db.add(attempt)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        reloaded = await _candidate_session_by_id(db, row.id)
        found = reloaded.candidate.quiz_attempt if reloaded.candidate is not None else None
        if found is None:
            raise QuizError("QUIZ_GENERATION_FAILED", "The skill quiz could not be prepared. Try again.", 502) from None
        return found
    await db.refresh(attempt)
    return attempt


async def _candidate_session(db: AsyncSession, claims: SessionClaims, session_id: uuid.UUID) -> InterviewSession:
    if claims.role != "candidate" or claims.session_id != session_id:
        raise QuizError("QUIZ_FORBIDDEN", "This link cannot open the skill quiz.", 403)
    row = await _candidate_session_by_id(db, session_id)
    candidate = row.candidate
    version = candidate.version if candidate is not None else None
    job = version.job if version is not None else None
    if candidate is None or version is None or job is None:
        raise QuizError("SESSION_NOT_FOUND", "This interview session is not available.", 404)
    if candidate.id != claims.candidate_id or job.id != claims.job_id:
        raise QuizError("QUIZ_FORBIDDEN", "This link cannot open the skill quiz.", 403)
    return row


async def _candidate_session_by_id(db: AsyncSession, session_id: uuid.UUID) -> InterviewSession:
    row = await db.scalar(
        select(InterviewSession)
        .where(InterviewSession.id == session_id)
        .options(
            selectinload(InterviewSession.candidate).selectinload(Candidate.parse_result),
            selectinload(InterviewSession.candidate).selectinload(Candidate.quiz_attempt),
            selectinload(InterviewSession.candidate).selectinload(Candidate.version).selectinload(JobVersion.queries),
            selectinload(InterviewSession.candidate).selectinload(Candidate.version).selectinload(JobVersion.job),
        )
    )
    if row is None:
        raise QuizError("SESSION_NOT_FOUND", "This interview session is not available.", 404)
    return row


def _locked_queries(version: JobVersion) -> list[JobChecklistQuery]:
    queries = sorted(version.queries, key=lambda item: int(item.query_id[1:]) if item.query_id[1:].isdigit() else 0)
    if version.locked_at is None or len(queries) != 10:
        raise QuizError(
            "CHECKLIST_NOT_LOCKED",
            "This role does not have a locked skill checklist yet.",
            409,
        )
    return queries


def _checklist(queries: list[JobChecklistQuery]) -> list[dict[str, str]]:
    return [
        {
            "query_id": item.query_id,
            "question": item.question,
            "dimension": item.dimension,
            "requirement_type": item.requirement_type,
            "scoring_rubric": item.scoring_rubric,
        }
        for item in queries
    ]


def _state(attempt: McqAttempt) -> AttemptState:
    try:
        paper = QuizPaper.model_validate({"questions": attempt.questions})
    except ValueError as exc:
        raise QuizError("QUIZ_INVALID", "The stored skill quiz could not be read.", 500) from exc
    answers = _stored_answers(attempt.answers)
    return AttemptState(
        paper=paper,
        answers=answers,
        correct_count=attempt.correct_count,
        score=attempt.score,
        started_at=attempt.started_at,
        submitted_at=attempt.submitted_at,
        time_limit_seconds=attempt.time_limit_seconds,
    )


def _stored_answers(raw: list[int | None] | None) -> tuple[int | None, ...] | None:
    if raw is None:
        return None
    cleaned: list[int | None] = []
    for item in raw:
        if item is None:
            cleaned.append(None)
            continue
        if isinstance(item, bool) or not isinstance(item, int) or item not in {0, 1, 2, 3}:
            raise QuizError("QUIZ_INVALID", "The stored skill quiz could not be read.", 500)
        cleaned.append(item)
    if len(cleaned) != 10:
        raise QuizError("QUIZ_INVALID", "The stored skill quiz could not be read.", 500)
    return tuple(cleaned)


def _apply(attempt: McqAttempt, state: AttemptState) -> None:
    attempt.answers = list(state.answers) if state.answers is not None else None
    attempt.correct_count = state.correct_count
    attempt.score = state.score
    attempt.submitted_at = state.submitted_at
