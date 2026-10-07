import asyncio
import hashlib
import logging
import secrets
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
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
from app.schemas.screening import CandidateGroupRead, CandidateRead, InviteRead, QueryEvaluationRead
from app.services.embeddings import Embedder
from app.services.invites import InviteSender, invitation_body
from app.services.ranking import RankInput, invite_ids, rank_candidates

logger = logging.getLogger(__name__)


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
    sender: InviteSender,
    version_id: uuid.UUID,
    message_id: str,
    from_address: str,
    filename: str,
    data: bytes,
    media_type: str,
) -> str:
    """Store one CV, score it against the locked checklist, and invite any new top-3 candidate."""
    digest = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(
        select(Candidate).where(
            Candidate.job_version_id == version_id,
            Candidate.content_sha256 == digest,
        )
    )
    if existing is not None:
        await _dispatch_invites(session, settings, sender, version_id)
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
    full_name = attributes.get("full_name")
    if isinstance(full_name, str) and full_name.strip():
        candidate.full_name = full_name.strip()[:255]
    _store_cv(settings, digest, filename, data, folder="processed")
    session.add(
        CandidateParseResult(
            id=uuid.uuid4(),
            candidate_id=candidate.id,
            status="parsed",
            parse_method=str(result.get("parse_method") or "native"),
            parse_confidence=float(result.get("parse_confidence") or 0),
            warnings=list(result.get("warnings") or []),
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
    await _dispatch_invites(session, settings, sender, version.id)
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
            selectinload(Candidate.version).selectinload(JobVersion.job),
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
        .options(selectinload(MagicLink.candidate).selectinload(Candidate.version).selectinload(JobVersion.job))
    )
    link = await session.scalar(statement)
    if link is None or link.candidate is None or link.candidate.version is None:
        return None
    job = link.candidate.version.job
    title = job.title if job is not None else ""
    return InviteRead(
        job_title=title,
        company_name=settings.company_name,
        status="invited",
        created_at=link.created_at,
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


async def _dispatch_invites(
    session: AsyncSession,
    settings: Settings,
    sender: InviteSender,
    version_id: uuid.UUID,
) -> None:
    version = await session.scalar(
        select(JobVersion).where(JobVersion.id == version_id).options(selectinload(JobVersion.job))
    )
    if version is None or version.job is None:
        return
    statement = (
        select(Candidate)
        .where(Candidate.job_version_id == version_id)
        .options(selectinload(Candidate.snapshot), selectinload(Candidate.magic_link))
    )
    candidates = list((await session.scalars(statement)).unique().all())
    ranks = {
        candidate.id: candidate.snapshot.rank
        for candidate in candidates
        if candidate.snapshot is not None and candidate.snapshot.rank is not None
    }
    invited = {candidate.id for candidate in candidates if candidate.magic_link is not None}
    for candidate_id in invite_ids(ranks, invited):
        candidate = next(item for item in candidates if item.id == candidate_id)
        if "@" not in candidate.email:
            continue
        token = secrets.token_urlsafe(32)
        url = f"{settings.public_app_url.rstrip('/')}/invite/{token}"
        await asyncio.to_thread(
            sender.send,
            candidate.email,
            f"Interview invitation: {version.job.title}",
            invitation_body(job_title=version.job.title, company_name=settings.company_name, url=url),
        )
        now = datetime.now(UTC)
        session.add(MagicLink(id=uuid.uuid4(), candidate_id=candidate.id, token=token, created_at=now))
        session.add(
            InterviewSession(
                id=uuid.uuid4(),
                candidate_id=candidate.id,
                job_version_id=version_id,
                status="invited",
                created_at=now,
            )
        )
        await session.flush()


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
    evaluations = []
    if snapshot is not None:
        evaluations = [
            QueryEvaluationRead(
                query_id=item.query_id,
                status=item.status,
                confidence=item.confidence,
                evidence=item.evidence,
                semantic_score=item.semantic_score,
            )
            for item in sorted(snapshot.evaluations, key=lambda item: int(item.query_id[1:]))
        ]
    return CandidateRead(
        id=candidate.id,
        email=candidate.email,
        full_name=candidate.full_name,
        rank=snapshot.rank if snapshot is not None else None,
        aggregate_score=snapshot.aggregate_score if snapshot is not None else None,
        must_have_ratio=snapshot.must_have_ratio if snapshot is not None else None,
        parse_status=parse_result.status if parse_result is not None else "pending",
        parse_method=parse_result.parse_method if parse_result is not None else "",
        invited=candidate.magic_link is not None,
        fairness_flags=list(snapshot.fairness_flags) if snapshot is not None else [],
        justifications=list(snapshot.justifications) if snapshot is not None else [],
        evaluations=evaluations,
        job_id=job_id,
        job_title=job_title,
    )
