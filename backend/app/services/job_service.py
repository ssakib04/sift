import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.graphs.job_creation_graph import (
    JobGraphError,
    PolicyRetriever,
    build_job_creation_graph,
    state_from_request,
)
from app.models.job import Job, JobChecklistQuery, JobPosting, JobVersion
from app.schemas.job import (
    ChecklistQuery,
    ChecklistQueryRead,
    JobCreateRequest,
    JobRead,
    JobVersionRead,
    JobVersionUpdate,
)
from app.services.interview_practice import is_practice_job
from app.services.job_rules import ensure_can_open_version, ensure_editable
from app.services.mcp_publish import McpPublishError, publish_via_mcp
from app.services.postajob import JobPoster, PostAJobError, PublishRequest, mailbox_apply_url
from app.services.telegram import TelegramError

logger = logging.getLogger(__name__)

_VERSION_LOAD = (
    selectinload(JobVersion.queries),
    selectinload(JobVersion.posting),
    selectinload(JobVersion.job),
)


async def create_job(
    session: AsyncSession,
    request: JobCreateRequest,
    *,
    llm: object,
    retriever: PolicyRetriever,
    settings: Settings,
) -> JobRead:
    from app.core.llm_fallback import FallbackLLMManager

    if not isinstance(llm, FallbackLLMManager):
        raise TypeError("Job creation requires FallbackLLMManager.")
    run = build_job_creation_graph(llm, retriever)
    try:
        result = await run(state_from_request(request))
    except JobGraphError:
        raise
    queries = _coerce_queries(result.get("queries"))
    now = datetime.now(UTC)
    job = Job(id=uuid.uuid4(), title=request.title, mail_subject=request.title.strip(), created_at=now)
    version = _version_from_request(
        job_id=job.id,
        request=request,
        version_number=1,
        description=str(result["description"]),
        excerpts=list(result.get("policy_excerpts") or []),
        llm_tier=str(result.get("llm_tier") or "unknown"),
        fallback_used=bool(result.get("fallback_used")),
        created_at=now,
    )
    version.queries = [_query_row(version.id, query) for query in queries]
    session.add(job)
    session.add(version)
    await session.commit()
    stored = await _require_job(session, job.id)
    return _to_job_read(stored, settings)


async def update_draft(
    session: AsyncSession,
    job_id: uuid.UUID,
    version_number: int,
    update: JobVersionUpdate,
    settings: Settings,
) -> JobRead:
    version = await _require_version(session, job_id, version_number)
    ensure_editable(version.status)
    if update.description is not None:
        version.description = update.description
    if update.queries is not None:
        for existing in list(version.queries):
            await session.delete(existing)
        await session.flush()
        version.queries = [_query_row(version.id, query) for query in update.queries]
    await session.commit()
    stored = await _require_job(session, job_id)
    return _to_job_read(stored, settings)


async def approve_version(
    session: AsyncSession,
    job_id: uuid.UUID,
    version_number: int,
    *,
    poster: JobPoster,
    settings: Settings,
) -> JobRead:
    job = await _require_job(session, job_id)
    version = _version_on(job, version_number)
    ensure_editable(version.status)
    version.status = "locked"
    version.locked_at = datetime.now(UTC)
    apply_url = mailbox_apply_url(settings.apply_to_address, job.mail_subject or job.title)
    version.posting = await _publish(
        version,
        job.title,
        apply_url,
        poster,
        settings,
        mail_subject=job.mail_subject,
    )
    await session.commit()
    stored = await _require_job(session, job_id)
    return _to_job_read(stored, settings)


async def open_next_version(session: AsyncSession, job_id: uuid.UUID, settings: Settings) -> JobRead:
    job = await _require_job(session, job_id)
    latest = _latest(job)
    ensure_can_open_version(latest.status)
    now = datetime.now(UTC)
    successor = JobVersion(
        id=uuid.uuid4(),
        job_id=job.id,
        version_number=latest.version_number + 1,
        status="draft",
        seniority=latest.seniority,
        required_skills=list(latest.required_skills),
        preferred_skills=list(latest.preferred_skills),
        qualifications=latest.qualifications,
        minimum_years=latest.minimum_years,
        technical_weight=latest.technical_weight,
        experience_weight=latest.experience_weight,
        qualification_weight=latest.qualification_weight,
        contract=latest.contract,
        category=latest.category,
        description=latest.description,
        policy_excerpts=list(latest.policy_excerpts),
        llm_tier=latest.llm_tier,
        fallback_used=latest.fallback_used,
        created_at=now,
        locked_at=None,
    )
    successor.queries = [
        JobChecklistQuery(
            version_id=successor.id,
            query_id=query.query_id,
            question=query.question,
            dimension=query.dimension,
            requirement_type=query.requirement_type,
            weight=query.weight,
            evidence_hints=list(query.evidence_hints),
            scoring_rubric=query.scoring_rubric,
        )
        for query in latest.queries
    ]
    job.versions.append(successor)
    await session.commit()
    stored = await _require_job(session, job_id)
    return _to_job_read(stored, settings)


async def list_jobs(session: AsyncSession, settings: Settings) -> list[JobRead]:
    statement = select(Job).options(selectinload(Job.versions).options(*_VERSION_LOAD)).order_by(Job.created_at.desc())
    jobs = list((await session.scalars(statement)).unique().all())
    return [_to_job_read(job, settings) for job in jobs if not is_practice_job(job.mail_subject)]


async def get_job(session: AsyncSession, job_id: uuid.UUID, settings: Settings) -> JobRead:
    return _to_job_read(await _require_job(session, job_id), settings)


def _coerce_queries(value: object) -> list[ChecklistQuery]:
    from app.schemas.job import ChecklistQuerySet

    if isinstance(value, list) and value and isinstance(value[0], ChecklistQuery):
        return ChecklistQuerySet(queries=value).queries
    return ChecklistQuerySet.model_validate({"queries": value}).queries


def _version_from_request(
    *,
    job_id: uuid.UUID,
    request: JobCreateRequest,
    version_number: int,
    description: str,
    excerpts: list[str],
    llm_tier: str,
    fallback_used: bool,
    created_at: datetime,
) -> JobVersion:
    return JobVersion(
        id=uuid.uuid4(),
        job_id=job_id,
        version_number=version_number,
        status="draft",
        seniority=request.seniority,
        required_skills=request.required_skills,
        preferred_skills=request.preferred_skills,
        qualifications=request.qualifications,
        minimum_years=request.minimum_years,
        technical_weight=request.technical_weight,
        experience_weight=request.experience_weight,
        qualification_weight=request.qualification_weight,
        contract=request.contract,
        category=request.category,
        description=description,
        policy_excerpts=excerpts,
        llm_tier=llm_tier,
        fallback_used=fallback_used,
        created_at=created_at,
        locked_at=None,
    )


def _query_row(version_id: uuid.UUID, query: ChecklistQuery) -> JobChecklistQuery:
    return JobChecklistQuery(
        version_id=version_id,
        query_id=query.query_id,
        question=query.question,
        dimension=query.dimension,
        requirement_type=query.requirement_type,
        weight=query.weight,
        evidence_hints=query.evidence_hints,
        scoring_rubric=query.scoring_rubric,
    )


async def _publish(
    version: JobVersion,
    title: str,
    apply_url: str,
    poster: JobPoster,
    settings: Settings,
    mail_subject: str = "",
) -> JobPosting:
    if len(version.description) < 100:
        return _posting(version.id, apply_url, status="skipped", detail="description_too_short")
    request = PublishRequest(
        title=title,
        description=version.description,
        apply_url=apply_url,
        contract=version.contract,
        category=version.category,
        company_name=settings.company_name,
        company_country=settings.company_country,
        seniority=version.seniority,
        skills=list(version.required_skills) + list(version.preferred_skills),
        version_id=str(version.id),
        apply_email=settings.apply_to_address,
        mail_subject=mail_subject.strip() or title,
    )
    if settings.mcp_server_url.strip():
        return await _publish_mcp(version.id, apply_url, request, settings)
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return await _publish_telegram(version.id, apply_url, request, poster, settings)
    if not settings.postajob_api_key:
        return _posting(version.id, apply_url, status="not_configured", detail="missing_api_key")
    try:
        result = await poster.publish(request)
    except PostAJobError as exc:
        logger.warning("postajob_publish_failed error_type=%s", type(exc).__name__)
        return _posting(version.id, apply_url, status="failed", detail=str(exc)[:128])
    except Exception as exc:
        logger.warning("postajob_publish_failed error_type=%s", type(exc).__name__)
        return _posting(version.id, apply_url, status="failed", detail=type(exc).__name__)
    return _posting(
        version.id,
        apply_url,
        status=result.status,
        external_id=result.external_id,
    )


async def _publish_mcp(
    version_id: uuid.UUID,
    apply_url: str,
    request: PublishRequest,
    settings: Settings,
) -> JobPosting:
    try:
        result = await publish_via_mcp(settings.mcp_server_url.strip(), request)
    except McpPublishError as exc:
        logger.warning("mcp_publish_failed error_type=%s", type(exc).__name__)
        return _posting(version_id, apply_url, provider="mcp", status="failed", detail=str(exc)[:128])
    except Exception as exc:
        logger.warning("mcp_publish_failed error_type=%s", type(exc).__name__)
        return _posting(version_id, apply_url, provider="mcp", status="failed", detail=type(exc).__name__)
    return _posting(
        version_id,
        apply_url,
        provider="mcp",
        status=result.status,
        external_id=result.external_id,
        detail=result.detail,
    )


async def _publish_telegram(
    version_id: uuid.UUID,
    apply_url: str,
    request: PublishRequest,
    poster: JobPoster,
    settings: Settings,
) -> JobPosting:
    try:
        result = await poster.publish(request)
    except TelegramError as exc:
        logger.warning("telegram_publish_failed error_type=%s", type(exc).__name__)
        return _posting(
            version_id,
            apply_url,
            provider="telegram",
            status="failed",
            detail=_redact(str(exc), settings.telegram_bot_token),
        )
    except Exception as exc:
        logger.warning("telegram_publish_failed error_type=%s", type(exc).__name__)
        return _posting(
            version_id,
            apply_url,
            provider="telegram",
            status="failed",
            detail=_redact(type(exc).__name__, settings.telegram_bot_token),
        )
    return _posting(
        version_id,
        apply_url,
        provider="telegram",
        status=result.status,
        external_id=result.external_id,
        detail=result.detail,
    )


def _redact(value: str, secret: str) -> str:
    if secret:
        value = value.replace(secret, "[redacted]")
    return value[:128]


def _posting(
    version_id: uuid.UUID,
    apply_url: str,
    *,
    status: str,
    detail: str | None = None,
    external_id: str | None = None,
    provider: str = "postajob",
) -> JobPosting:
    return JobPosting(
        version_id=version_id,
        provider=provider,
        external_id=external_id,
        status=status,
        apply_url=apply_url,
        detail=detail,
    )


async def _require_job(session: AsyncSession, job_id: uuid.UUID) -> Job:
    statement = select(Job).where(Job.id == job_id).options(selectinload(Job.versions).options(*_VERSION_LOAD))
    job = await session.scalar(statement)
    if job is None:
        raise KeyError(job_id)
    return job


async def _require_version(session: AsyncSession, job_id: uuid.UUID, version_number: int) -> JobVersion:
    return _version_on(await _require_job(session, job_id), version_number)


def _version_on(job: Job, version_number: int) -> JobVersion:
    for version in job.versions:
        if version.version_number == version_number:
            return version
    raise KeyError((job.id, version_number))


def _latest(job: Job) -> JobVersion:
    return max(job.versions, key=lambda version: version.version_number)


def _to_job_read(job: Job, settings: Settings) -> JobRead:
    versions = sorted(job.versions, key=lambda version: version.version_number)
    return JobRead(
        id=job.id,
        title=job.title,
        mail_subject=job.mail_subject,
        apply_email=settings.apply_to_address,
        created_at=job.created_at,
        versions=[_to_version_read(version) for version in versions],
    )


def _to_version_read(version: JobVersion) -> JobVersionRead:
    queries = sorted(version.queries, key=lambda query: int(query.query_id[1:]))
    posting = version.posting
    return JobVersionRead(
        id=version.id,
        version_number=version.version_number,
        status=version.status,
        seniority=version.seniority,
        required_skills=list(version.required_skills),
        preferred_skills=list(version.preferred_skills),
        qualifications=version.qualifications,
        minimum_years=version.minimum_years,
        technical_weight=version.technical_weight,
        experience_weight=version.experience_weight,
        qualification_weight=version.qualification_weight,
        contract=version.contract,
        category=version.category,
        description=version.description,
        queries=[
            ChecklistQueryRead(
                query_id=query.query_id,
                question=query.question,
                dimension=query.dimension,
                requirement_type=query.requirement_type,
                weight=query.weight,
                evidence_hints=list(query.evidence_hints),
                scoring_rubric=query.scoring_rubric,
            )
            for query in queries
        ],
        llm_tier=version.llm_tier,
        fallback_used=version.fallback_used,
        created_at=version.created_at,
        locked_at=version.locked_at,
        posting_status=None if posting is None else posting.status,
        posting_detail=None if posting is None else posting.detail,
        external_posting_id=None if posting is None else posting.external_id,
        apply_url=None if posting is None else posting.apply_url,
    )

