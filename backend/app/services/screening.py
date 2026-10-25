import asyncio
import hashlib
import logging
import re
import secrets
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.llm_fallback import FallbackLLMManager, LLMFallbackExhaustedError
from app.graphs.cv_screening_graph import CVGraphError, build_cv_screening_graph
from app.graphs.job_creation_graph import JobGraphError
from app.models.candidate import (
    Candidate,
    CandidateDocument,
    CandidateParseResult,
    IntakeMessage,
    InterviewSession,
    MagicLink,
    QueryEvaluation,
    ScoreSnapshot,
)
from app.models.job import JobChecklistQuery, JobVersion
from app.schemas.screening import (
    CandidateGroupRead,
    CandidateRead,
    InviteBatchRead,
    InviteRead,
    InviteSkipRead,
    QueryEvaluationRead,
)
from app.services.calendar import GoogleCalendarClient
from app.services.cv_claims import store_cv_claims
from app.services.embeddings import Embedder
from app.services.face_embed import FaceEmbedder, create_face_embedder
from app.services.identification import store_candidate_face, store_candidate_profile
from app.services.interview_booking import remote_busy, reserve_call, taken_windows
from app.services.invites import InviteSender
from app.services.ranking import RankInput, rank_candidates
from app.services.report_progress import visible_report_progress
from app.services.schedule import BusyWindow, format_schedule, interview_zone

logger = logging.getLogger(__name__)
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def contact_email(given: str, attributes: dict[str, object], raw_text: str) -> str:
    """Prefer the sender address, then the address written on the CV."""
    for candidate in (given, str(attributes.get("email") or ""), raw_text):
        match = _EMAIL.search(candidate)
        if match is not None:
            return match.group(0)[:320]
    return given.strip()[:320]


class InviteError(Exception):
    """A recruiter selection cannot be invited."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def invite_block_reason(*, email: str, already_invited: bool, scored: bool) -> str | None:
    """Return why this applicant cannot be invited, or None when the mail can be sent."""
    if already_invited:
        return "already_invited"
    if not scored:
        return "not_scored"
    if "@" not in email:
        return "no_email"
    return None


@dataclass(frozen=True)
class JobMailKey:
    job_id: uuid.UUID
    mail_subject: str
    version_id: uuid.UUID
    title: str
    locked_at: datetime


async def load_mail_keys(session: AsyncSession) -> list[JobMailKey]:
    statement = (
        select(JobVersion)
        .where(JobVersion.status == "locked")
        .options(selectinload(JobVersion.job))
    )
    versions = list((await session.scalars(statement)).unique().all())
    latest: dict[uuid.UUID, JobVersion] = {}
    for version in versions:
        current = latest.get(version.job_id)
        if current is None or version.version_number > current.version_number:
            latest[version.job_id] = version
    keys: list[JobMailKey] = []
    for version in latest.values():
        job = version.job
        if job is None:
            continue
        keys.append(
            JobMailKey(
                job_id=job.id,
                mail_subject=job.mail_subject,
                version_id=version.id,
                title=job.title,
                locked_at=version.locked_at or version.created_at,
            )
        )
    return keys


async def message_seen(session: AsyncSession, message_id: str) -> bool:
    existing = await session.get(IntakeMessage, message_id)
    return existing is not None


async def record_intake(
    session: AsyncSession,
    message_id: str,
    status: str,
    version_id: uuid.UUID | None,
) -> None:
    session.add(
        IntakeMessage(
            message_id=message_id,
            status=status,
            job_version_id=version_id,
            created_at=datetime.now(UTC),
        )
    )


async def accept_cv(
    session: AsyncSession,
    settings: Settings,
    *,
    llm: FallbackLLMManager,
    embedder: Embedder,
    face_embedder: FaceEmbedder | None = None,
    version_id: uuid.UUID,
    message_id: str,
    from_address: str,
    filename: str,
    data: bytes,
    media_type: str,
) -> str:
    """Store one CV and score it against the locked checklist. Invitations stay with the recruiter."""
    digest = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(
        select(Candidate).where(
            Candidate.job_version_id == version_id,
            Candidate.content_sha256 == digest,
        )
    )
    if existing is not None:
        return "duplicate"

    version = await session.scalar(
        select(JobVersion)
        .where(JobVersion.id == version_id, JobVersion.status == "locked")
        .options(selectinload(JobVersion.queries), selectinload(JobVersion.job))
    )
    if version is None or version.job is None:
        return "ignored"

    stored_path = _store_cv(settings, digest, filename, data, folder="raw")
    now = datetime.now(UTC)
    candidate = Candidate(
        id=uuid.uuid4(),
        job_version_id=version.id,
        email=from_address.strip(),
        full_name="",
        content_sha256=digest,
        source_message_id=message_id,
        created_at=now,
    )
    session.add(candidate)
    session.add(
        CandidateDocument(
            id=uuid.uuid4(),
            candidate_id=candidate.id,
            filename=Path(filename).name,
            media_type=media_type,
            storage_path=stored_path,
            size_bytes=len(data),
        )
    )
    await session.flush()
    run = build_cv_screening_graph(llm, embedder)
    try:
        result = await run(
            {
                "filename": filename,
                "file_bytes": data,
                "job_description": version.description,
                "locked_checklist": [_query_payload(query) for query in version.queries],
            }
        )
    except (CVGraphError, JobGraphError, LLMFallbackExhaustedError) as exc:
        logger.warning("cv_score_failed error_type=%s", type(exc).__name__)
        _store_cv(settings, digest, filename, data, folder="failed")
        session.add(_failed_parse(candidate.id, str(exc)))
        return "parse_failed"

    errors = result.get("errors") or []
    if errors or not result.get("raw_text"):
        _store_cv(settings, digest, filename, data, folder="failed")
        session.add(
            _failed_parse(candidate.id, "; ".join(errors) or "The CV did not contain extractable text.")
        )
        return "parse_failed"

    attributes = result.get("extracted_attributes") or {}
    if not isinstance(attributes, dict):
        attributes = {}
    full_name = attributes.get("full_name")
    if isinstance(full_name, str) and full_name.strip():
        candidate.full_name = full_name.strip()[:255]
    candidate.email = contact_email(candidate.email, attributes, str(result.get("raw_text") or ""))
    _store_cv(settings, digest, filename, data, folder="processed")
    session.add(store_candidate_profile(candidate.id, attributes))
    store_cv_claims(session, candidate.id, attributes, str(result.get("raw_text") or ""))
    face_row, face_warning = store_candidate_face(
        settings.cv_storage_dir,
        candidate.id,
        filename,
        data,
        face_embedder or _face_embedder(settings),
        now=now,
    )
    if face_row is not None:
        session.add(face_row)
    warnings = list(result.get("warnings") or [])
    if face_warning:
        warnings.append(face_warning)
    session.add(
        CandidateParseResult(
            id=uuid.uuid4(),
            candidate_id=candidate.id,
            status="parsed",
            parse_method=str(result.get("parse_method") or "native"),
            parse_confidence=float(result.get("parse_confidence") or 0),
            warnings=warnings,
            raw_text=str(result.get("raw_text") or ""),
        )
    )
    snapshot = ScoreSnapshot(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        job_version_id=version.id,
        aggregate_score=float(result.get("aggregate_score") or 0),
        must_have_ratio=float(result.get("must_have_ratio") or 0),
        technical_score=float(result.get("technical_score") or 0),
        experience_score=float(result.get("experience_score") or 0),
        qualification_score=float(result.get("qualification_score") or 0),
        fairness_flags=list(result.get("fairness_flags") or []),
        justifications=list(result.get("justifications") or []),
        llm_tier=str(result.get("llm_tier") or "unknown"),
        fallback_used=bool(result.get("fallback_used")),
        rank=None,
        created_at=now,
    )
    session.add(snapshot)
    for item in result.get("query_evaluations") or []:
        session.add(
            QueryEvaluation(
                id=uuid.uuid4(),
                snapshot_id=snapshot.id,
                query_id=str(item["query_id"]),
                status=str(item["status"]),
                confidence=float(item["confidence"]),
                evidence=str(item["evidence"]),
                semantic_score=float(item["semantic_score"]),
            )
        )
    await session.flush()
    await _rerank(session, version.id)
    return "scored"


async def list_ranked_candidates(session: AsyncSession, job_id: uuid.UUID) -> list[CandidateRead]:
    keys = [key for key in await load_mail_keys(session) if key.job_id == job_id]
    if not keys:
        return []
    statement = (
        select(Candidate)
        .where(Candidate.job_version_id == keys[0].version_id)
        .options(
            selectinload(Candidate.parse_result),
            selectinload(Candidate.snapshot).selectinload(ScoreSnapshot.evaluations),
            selectinload(Candidate.magic_link),
            selectinload(Candidate.quiz_attempt),
            selectinload(Candidate.interview_session),
            selectinload(Candidate.version).selectinload(JobVersion.queries),
            selectinload(Candidate.face),
        )
    )
    candidates = list((await session.scalars(statement)).unique().all())
    candidates.sort(key=lambda candidate: (candidate.snapshot.rank if candidate.snapshot and candidate.snapshot.rank else 10_000, candidate.created_at))
    return [
        _to_candidate_read(candidate, job_id=keys[0].job_id, job_title=keys[0].title) for candidate in candidates
    ]


async def list_candidate_groups(session: AsyncSession) -> list[CandidateGroupRead]:
    groups: list[CandidateGroupRead] = []
    for key in await load_mail_keys(session):
        candidates = await list_ranked_candidates(session, key.job_id)
        if not candidates:
            continue
        groups.append(
            CandidateGroupRead(
                job_id=key.job_id,
                job_title=key.title,
                mail_subject=key.mail_subject,
                candidates=candidates,
            )
        )
    groups.sort(key=lambda group: group.job_title.casefold())
    return groups


async def get_candidate(session: AsyncSession, candidate_id: uuid.UUID) -> CandidateRead | None:
    statement = (
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .options(
            selectinload(Candidate.parse_result),
            selectinload(Candidate.snapshot).selectinload(ScoreSnapshot.evaluations),
            selectinload(Candidate.magic_link),
            selectinload(Candidate.quiz_attempt),
            selectinload(Candidate.interview_session),
            selectinload(Candidate.version).selectinload(JobVersion.job),
            selectinload(Candidate.version).selectinload(JobVersion.queries),
            selectinload(Candidate.face),
        )
    )
    candidate = await session.scalar(statement)
    if candidate is None:
        return None
    job = candidate.version.job if candidate.version is not None else None
    return _to_candidate_read(
        candidate,
        job_id=job.id if job is not None else None,
        job_title=job.title if job is not None else "",
    )


async def resolve_invite(session: AsyncSession, token: str, settings: Settings) -> InviteRead | None:
    statement = (
        select(MagicLink)
        .where(MagicLink.token == token)
        .options(
            selectinload(MagicLink.candidate).selectinload(Candidate.version).selectinload(JobVersion.job),
            selectinload(MagicLink.candidate).selectinload(Candidate.interview_session),
            selectinload(MagicLink.candidate).selectinload(Candidate.face),
        )
    )
    link = await session.scalar(statement)
    if link is None or link.candidate is None or link.candidate.version is None:
        return None
    job = link.candidate.version.job
    title = job.title if job is not None else ""
    interview = link.candidate.interview_session
    return InviteRead(
        job_title=title,
        company_name=settings.company_name,
        status="invited",
        created_at=link.created_at,
        scheduled_label=_scheduled_label(
            interview.scheduled_start if interview is not None else None,
            interview.scheduled_end if interview is not None else None,
        ),
        face_check_required=link.candidate.face is not None,
    )


async def _rerank(session: AsyncSession, version_id: uuid.UUID) -> dict[uuid.UUID, int]:
    statement = (
        select(ScoreSnapshot, Candidate.created_at)
        .join(Candidate, Candidate.id == ScoreSnapshot.candidate_id)
        .where(ScoreSnapshot.job_version_id == version_id)
    )
    pairs = list((await session.execute(statement)).all())
    ranks = rank_candidates(
        [
            RankInput(
                candidate_id=snapshot.candidate_id,
                aggregate_score=snapshot.aggregate_score,
                must_have_ratio=snapshot.must_have_ratio,
                technical_score=snapshot.technical_score,
                experience_score=snapshot.experience_score,
                qualification_score=snapshot.qualification_score,
                created_at=created_at,
            )
            for snapshot, created_at in pairs
        ]
    )
    for snapshot, _created_at in pairs:
        snapshot.rank = ranks[snapshot.candidate_id]
    return ranks


async def invite_selected(
    session: AsyncSession,
    settings: Settings,
    sender: InviteSender,
    job_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
) -> InviteBatchRead:
    """Mail interview links to the applicants the recruiter chose."""
    unique_ids = list(dict.fromkeys(candidate_ids))
    if not unique_ids:
        raise InviteError("INVITE_EMPTY", "Choose at least one applicant.")
    matched = next((key for key in await load_mail_keys(session) if key.job_id == job_id), None)
    if matched is None:
        raise InviteError("JOB_NOT_LOCKED", "Only a locked job can send invitations.")
    version = await session.scalar(
        select(JobVersion).where(JobVersion.id == matched.version_id).options(selectinload(JobVersion.job))
    )
    if version is None or version.job is None:
        raise InviteError("JOB_NOT_LOCKED", "Only a locked job can send invitations.")
    statement = (
        select(Candidate)
        .where(Candidate.id.in_(unique_ids))
        .options(selectinload(Candidate.snapshot), selectinload(Candidate.magic_link))
    )
    found = {item.id: item for item in (await session.scalars(statement)).unique().all()}
    now = datetime.now(UTC)
    busy: list[BusyWindow] = await taken_windows(session, now)
    calendar = GoogleCalendarClient(settings)
    busy.extend(await asyncio.to_thread(remote_busy, calendar, now))
    invited: list[uuid.UUID] = []
    skipped: list[InviteSkipRead] = []
    for candidate_id in unique_ids:
        candidate = found.get(candidate_id)
        if candidate is None or candidate.job_version_id != matched.version_id:
            skipped.append(InviteSkipRead(candidate_id=candidate_id, reason="missing"))
            continue
        reason = invite_block_reason(
            email=candidate.email,
            already_invited=candidate.magic_link is not None,
            scored=candidate.snapshot is not None,
        )
        if reason is not None:
            skipped.append(InviteSkipRead(candidate_id=candidate_id, reason=reason))
            continue
        token = secrets.token_urlsafe(32)
        url = f"{settings.public_app_url.rstrip('/')}/invite/{token}"
        reserved = await asyncio.to_thread(
            reserve_call,
            settings,
            sender,
            candidate_name=candidate.full_name,
            candidate_email=candidate.email,
            job_title=version.job.title,
            url=url,
            busy=list(busy),
            now=now,
            candidate_id=candidate.id,
            calendar=calendar,
        )
        if reserved is None:
            skipped.append(InviteSkipRead(candidate_id=candidate_id, reason="calendar_full"))
            continue
        busy.append(BusyWindow(start=reserved.start, end=reserved.end))
        session.add(MagicLink(id=uuid.uuid4(), candidate_id=candidate.id, token=token, created_at=now))
        session.add(
            InterviewSession(
                id=uuid.uuid4(),
                candidate_id=candidate.id,
                job_version_id=matched.version_id,
                status="invited",
                created_at=now,
                processing_status="",
                copilot_explored=[],
                copilot_gaps=[],
                copilot_question="",
                copilot_turn_count=-1,
                scheduled_start=reserved.start,
                scheduled_end=reserved.end,
                calendar_event_id=reserved.event_id,
                calendar_url=reserved.calendar_url,
            )
        )
        await session.flush()
        invited.append(candidate_id)
    return InviteBatchRead(invited=invited, skipped=skipped)


def _face_embedder(settings: Settings) -> FaceEmbedder:
    return create_face_embedder(settings)


def _store_cv(settings: Settings, digest: str, filename: str, data: bytes, *, folder: str) -> str:
    suffix = Path(filename).suffix.lower()
    target = Path(settings.cv_storage_dir) / folder / f"{digest}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if folder == "raw" or not target.exists():
        if folder == "raw":
            target.write_bytes(data)
        else:
            raw = Path(settings.cv_storage_dir) / "raw" / f"{digest}{suffix}"
            if raw.exists():
                shutil.copy(raw, target)
            else:
                target.write_bytes(data)
    return str(target)


def _failed_parse(candidate_id: uuid.UUID, warning: str) -> CandidateParseResult:
    return CandidateParseResult(
        id=uuid.uuid4(),
        candidate_id=candidate_id,
        status="parse_failed",
        parse_method="failed",
        parse_confidence=0,
        warnings=[warning],
        raw_text="",
    )


def _query_payload(query: JobChecklistQuery) -> dict[str, object]:
    return {
        "query_id": query.query_id,
        "question": query.question,
        "dimension": query.dimension,
        "requirement_type": query.requirement_type,
        "weight": query.weight,
        "evidence_hints": list(query.evidence_hints),
        "scoring_rubric": query.scoring_rubric,
    }


def _to_candidate_read(
    candidate: Candidate,
    *,
    job_id: uuid.UUID | None = None,
    job_title: str = "",
) -> CandidateRead:
    snapshot = candidate.snapshot
    parse_result = candidate.parse_result
    questions = {
        query.query_id: query.question
        for query in (candidate.version.queries if candidate.version is not None else [])
    }
    evaluations = []
    if snapshot is not None:
        evaluations = [
            QueryEvaluationRead(
                query_id=item.query_id,
                question=questions.get(item.query_id, ""),
                status=item.status,
                confidence=item.confidence,
                evidence=item.evidence,
                semantic_score=item.semantic_score,
            )
            for item in sorted(snapshot.evaluations, key=lambda item: int(item.query_id[1:]))
        ]
    interview = candidate.interview_session
    return CandidateRead(
        id=candidate.id,
        email=candidate.email,
        full_name=candidate.full_name,
        rank=snapshot.rank if snapshot is not None else None,
        aggregate_score=snapshot.aggregate_score if snapshot is not None else None,
        mcq_score=(
            candidate.quiz_attempt.score
            if candidate.quiz_attempt is not None and candidate.quiz_attempt.submitted_at is not None
            else None
        ),
        must_have_ratio=snapshot.must_have_ratio if snapshot is not None else None,
        parse_status=parse_result.status if parse_result is not None else "pending",
        parse_method=parse_result.parse_method if parse_result is not None else "",
        invited=candidate.magic_link is not None,
        has_photo=_photo_ready(candidate),
        fairness_flags=list(snapshot.fairness_flags) if snapshot is not None else [],
        justifications=list(snapshot.justifications) if snapshot is not None else [],
        evaluations=evaluations,
        job_id=job_id,
        job_title=job_title,
        created_at=candidate.created_at,
        scheduled_label=_scheduled_label(
            interview.scheduled_start if interview is not None else None,
            interview.scheduled_end if interview is not None else None,
        ),
        interview_status=interview.status if interview is not None else "",
        report_progress=visible_report_progress(
            interview.status if interview is not None else "",
            interview.report_progress if interview is not None else None,
        ),
    )


def _photo_ready(candidate: Candidate) -> bool:
    from sqlalchemy import inspect as sa_inspect

    if "face" in sa_inspect(candidate).unloaded:
        return False
    face = candidate.face
    if face is None or not face.storage_path:
        return False
    return Path(face.storage_path).is_file()


def _scheduled_label(start: datetime | None, end: datetime | None) -> str:
    return format_schedule(start, end, interview_zone(get_settings().interview_timezone))
