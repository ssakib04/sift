import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.llm_fallback import FallbackLLMManager
from app.core.session_tokens import SessionClaims, issue_session_token
from app.models.candidate import Candidate, InterviewAnalysis, InterviewSession, MagicLink, TranscriptSegment
from app.models.job import JobChecklistQuery, JobVersion
from app.services.interview_analysis import AnalysisDraft, draft_for_transcript
from app.services.interview_livekit import issue_livekit_token
from app.services.interview_copilot import CopilotDraft, copilot_from_transcript
from app.services.interview_rules import (
    InterviewError,
    SessionClock,
    assert_recruiter,
    bind_ice_host,
    can_store_audio,
    copilot_cache_matches,
    end_clock,
    format_transcript,
    ice_servers,
    start_clock,
)


@dataclass(frozen=True)
class OpenedSession:
    session_id: uuid.UUID
    token: str
    role: str
    status: str
    job_title: str
    company_name: str
    ice_servers: list[dict[str, str]]
    livekit_url: str
    livekit_token: str


@dataclass(frozen=True)
class SessionDetail:
    session_id: uuid.UUID
    role: str
    status: str
    job_title: str
    company_name: str
    ice_servers: list[dict[str, str]]
    livekit_url: str
    livekit_token: str
    consented_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None


async def open_candidate_session(
    db: AsyncSession,
    settings: Settings,
    magic_token: str,
    host: str,
) -> OpenedSession | None:
    if not magic_token or len(magic_token) > 128:
        return None
    link = await db.scalar(
        select(MagicLink)
        .where(MagicLink.token == magic_token)
        .options(
            selectinload(MagicLink.candidate).selectinload(Candidate.interview_session),
            selectinload(MagicLink.candidate).selectinload(Candidate.version).selectinload(JobVersion.job),
        )
    )
    if link is None or link.candidate is None or link.candidate.interview_session is None:
        return None
    return _opened(settings, link.candidate, "candidate", host)


async def open_recruiter_session(
    db: AsyncSession,
    settings: Settings,
    candidate_id: uuid.UUID,
    host: str,
) -> OpenedSession | None:
    candidate = await db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .options(
            selectinload(Candidate.magic_link),
            selectinload(Candidate.interview_session),
            selectinload(Candidate.version).selectinload(JobVersion.job),
        )
    )
    if candidate is None or candidate.magic_link is None or candidate.interview_session is None:
        return None
    return _opened(settings, candidate, "recruiter", host)


async def session_detail(db: AsyncSession, settings: Settings, claims: SessionClaims, host: str) -> SessionDetail:
    row, job_title, _job_id = await _require(db, claims)
    livekit_url, livekit_token = issue_livekit_token(settings, room=str(row.id), role=claims.role)
    return SessionDetail(
        session_id=row.id,
        role=claims.role,
        status=row.status,
        job_title=job_title,
        company_name=settings.company_name,
        ice_servers=bind_ice_host(ice_servers(settings), host),
        livekit_url=livekit_url,
        livekit_token=livekit_token,
        consented_at=row.consented_at,
        started_at=row.started_at,
        ended_at=row.ended_at,
    )


async def start_interview(db: AsyncSession, claims: SessionClaims, *, consent: bool) -> str:
    row, _title, _job_id = await _require(db, claims)
    clock = start_clock(_clock(row), consent=consent, now=datetime.now(UTC))
    _apply_clock(row, clock)
    await db.commit()
    return row.status


async def end_interview(db: AsyncSession, llm: FallbackLLMManager, claims: SessionClaims) -> str:
    row, _title, _job_id = await _require(db, claims)
    if row.status == "ended":
        return row.status
    clock = end_clock(_clock(row), now=datetime.now(UTC))
    segments = await _segment_rows(db, row.id)
    questions = await _questions(db, row.job_version_id)
    try:
        draft = await draft_for_transcript(llm, questions, format_transcript(_lines(segments)))
        failed = False
    except Exception as exc:
        draft = None
        failed = True
        _log_analysis_failure(exc)
    _apply_clock(row, clock)
    if failed or draft is None:
        row.processing_status = "failed"
    else:
        await _save_analysis(db, row, draft)
        row.processing_status = "complete"
    await db.commit()
    return row.status


async def list_transcript(db: AsyncSession, claims: SessionClaims) -> list[TranscriptSegment]:
    assert_recruiter(claims.role)
    row, _title, _job_id = await _require(db, claims)
    return await _segment_rows(db, row.id)


async def interview_copilot(db: AsyncSession, llm: FallbackLLMManager, claims: SessionClaims) -> CopilotDraft:
    assert_recruiter(claims.role)
    row, _title, _job_id = await _require(db, claims)
    segments = await _segment_rows(db, row.id)
    if copilot_cache_matches(row.copilot_turn_count, len(segments)):
        return CopilotDraft(
            explored=list(row.copilot_explored or []),
            gaps=list(row.copilot_gaps or []),
            suggested_question=row.copilot_question,
        )
    questions = await _questions(db, row.job_version_id)
    draft = await copilot_from_transcript(llm, questions, format_transcript(_lines(segments)))
    row.copilot_explored = draft.explored
    row.copilot_gaps = draft.gaps
    row.copilot_question = draft.suggested_question
    row.copilot_turn_count = len(segments)
    await db.commit()
    return draft


async def read_analysis(db: AsyncSession, claims: SessionClaims) -> InterviewAnalysis | None:
    assert_recruiter(claims.role)
    row, _title, _job_id = await _require(db, claims)
    return await db.scalar(select(InterviewAnalysis).where(InterviewAnalysis.session_id == row.id))


async def audio_status(db: AsyncSession, claims: SessionClaims) -> str:
    row, _title, _job_id = await _require(db, claims)
    return row.status


async def store_transcript_line(
    db: AsyncSession,
    claims: SessionClaims,
    *,
    speaker: str,
    start_time: float,
    end_time: float,
    text: str,
    confidence: float,
) -> TranscriptSegment | None:
    row, _title, _job_id = await _require(db, claims)
    if not can_store_audio(row.status):
        raise InterviewError("CONSENT_REQUIRED", "The candidate has not consented yet.", 409)
    cleaned = text.strip()
    if not cleaned:
        return None
    segment = TranscriptSegment(
        id=uuid.uuid4(),
        session_id=row.id,
        speaker=speaker,
        start_time=start_time,
        end_time=end_time,
        text=cleaned,
        confidence=confidence,
        created_at=datetime.now(UTC),
    )
    db.add(segment)
    await db.commit()
    return segment


def _opened(settings: Settings, candidate: Candidate, role: str, host: str) -> OpenedSession | None:
    session_row = candidate.interview_session
    version = candidate.version
    job = version.job if version is not None else None
    if session_row is None or version is None or job is None:
        return None
    if not settings.jwt_secret:
        raise InterviewError("INTERVIEW_UNAVAILABLE", "Interview access is not configured.", 503)
    token = issue_session_token(
        role=role,
        candidate_id=candidate.id,
        job_id=job.id,
        session_id=session_row.id,
        secret=settings.jwt_secret,
        ttl_minutes=settings.jwt_ttl_minutes,
    )
    livekit_url, livekit_token = issue_livekit_token(settings, room=str(session_row.id), role=role)
    return OpenedSession(
        session_id=session_row.id,
        token=token,
        role=role,
        status=session_row.status,
        job_title=job.title,
        company_name=settings.company_name,
        ice_servers=bind_ice_host(ice_servers(settings), host),
        livekit_url=livekit_url,
        livekit_token=livekit_token,
    )


async def _require(db: AsyncSession, claims: SessionClaims) -> tuple[InterviewSession, str, uuid.UUID]:
    row = await db.scalar(
        select(InterviewSession)
        .where(InterviewSession.id == claims.session_id)
        .options(selectinload(InterviewSession.candidate).selectinload(Candidate.version).selectinload(JobVersion.job))
    )
    if row is None or row.candidate is None or row.candidate.version is None or row.candidate.version.job is None:
        raise InterviewError("SESSION_NOT_FOUND", "This interview session is not available.", 404)
    job = row.candidate.version.job
    if row.candidate_id != claims.candidate_id or job.id != claims.job_id:
        raise InterviewError("INTERVIEW_FORBIDDEN", "This link does not match the interview.", 403)
    return row, job.title, job.id


def _clock(row: InterviewSession) -> SessionClock:
    return SessionClock(
        status=row.status,
        consented_at=row.consented_at,
        started_at=row.started_at,
        ended_at=row.ended_at,
        processing_status=row.processing_status or "",
    )


def _apply_clock(row: InterviewSession, clock: SessionClock) -> None:
    row.status = clock.status
    row.consented_at = clock.consented_at
    row.started_at = clock.started_at
    row.ended_at = clock.ended_at
    if clock.processing_status:
        row.processing_status = clock.processing_status


async def _segment_rows(db: AsyncSession, session_id: uuid.UUID) -> list[TranscriptSegment]:
    result = await db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.start_time, TranscriptSegment.created_at)
    )
    return list(result.all())


def _lines(segments: list[TranscriptSegment]) -> list[tuple[str, float, float, str]]:
    return [(segment.speaker, segment.start_time, segment.end_time, segment.text) for segment in segments]


async def _questions(db: AsyncSession, version_id: uuid.UUID) -> list[str]:
    result = await db.scalars(
        select(JobChecklistQuery)
        .where(JobChecklistQuery.version_id == version_id)
        .order_by(JobChecklistQuery.query_id)
    )
    return [query.question for query in result.all()]


async def _save_analysis(db: AsyncSession, row: InterviewSession, draft: AnalysisDraft) -> None:
    existing = await db.scalar(select(InterviewAnalysis).where(InterviewAnalysis.session_id == row.id))
    if existing is not None:
        return
    db.add(
        InterviewAnalysis(
            id=uuid.uuid4(),
            session_id=row.id,
            relevance=draft.relevance,
            technical_accuracy=draft.technical_accuracy,
            completeness=draft.completeness,
            articulation=draft.articulation,
            gaps=draft.gaps,
            summary=draft.summary,
            llm_tier=draft.llm_tier,
            fallback_used=draft.fallback_used,
            created_at=datetime.now(UTC),
        )
    )


def _log_analysis_failure(exc: Exception) -> None:
    import logging

    logging.getLogger(__name__).warning("interview_analysis_failed error_type=%s", type(exc).__name__)
