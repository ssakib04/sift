"""Recruiter notices for applicants who have just registered."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import ApplicantNotification, Candidate
from app.models.job import Job, JobVersion
from app.schemas.notice import ApplicantNoticeListRead, ApplicantNoticeRead
from app.services.interview_practice import is_practice_job


def ordinal(rank: int) -> str:
    if 10 <= rank % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


def ranking_notice_message(*, job_title: str, scored: int, unreadable: int) -> str:
    """One notice after a batch is scored, before anyone is invited."""
    role = job_title.strip() or "a role"
    noun = "CV" if scored == 1 else "CVs"
    unread = ""
    if unreadable > 0:
        failed = "CV" if unreadable == 1 else "CVs"
        unread = f" {unreadable} {failed} could not be read."
    return f"{scored} {noun} scored for {role}.{unread} Review the ranking and choose who to invite."


def notice_message(*, full_name: str, email: str, job_title: str, rank: int | None) -> str:
    who = full_name.strip() or email.strip() or "Someone"
    role = job_title.strip() or "a role"
    if rank is None or rank < 1:
        return f"{who} has applied for {role} and is waiting to be placed."
    return f"{who} has applied for {role} and is sitting in {ordinal(rank)} position."


async def record_ranking_notice(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    summary: str,
    now: datetime,
) -> None:
    session.add(
        ApplicantNotification(
            id=uuid.uuid4(),
            candidate_id=None,
            job_id=job_id,
            summary=summary,
            created_at=now,
            read_at=None,
        )
    )
    await session.flush()


async def record_applicant_notice(session: AsyncSession, candidate_id: uuid.UUID, now: datetime) -> None:
    existing = await session.scalar(
        select(ApplicantNotification.id).where(ApplicantNotification.candidate_id == candidate_id)
    )
    if existing is not None:
        return
    session.add(
        ApplicantNotification(
            id=uuid.uuid4(),
            candidate_id=candidate_id,
            created_at=now,
            read_at=None,
        )
    )
    await session.flush()


async def list_notices(session: AsyncSession) -> ApplicantNoticeListRead:
    unread = await session.scalar(
        select(func.count())
        .select_from(ApplicantNotification)
        .where(ApplicantNotification.read_at.is_(None))
    )
    statement = (
        select(ApplicantNotification)
        .options(
            selectinload(ApplicantNotification.candidate).selectinload(Candidate.snapshot),
            selectinload(ApplicantNotification.candidate)
            .selectinload(Candidate.version)
            .selectinload(JobVersion.job),
            selectinload(ApplicantNotification.job),
        )
        .order_by(ApplicantNotification.read_at.asc().nulls_first(), ApplicantNotification.created_at.desc())
        .limit(40)
    )
    rows = list((await session.scalars(statement)).unique().all())
    notices = [item for item in (_to_read(row) for row in rows) if item is not None]
    return ApplicantNoticeListRead(unread_count=int(unread or 0), notices=notices)


async def mark_notice_read(session: AsyncSession, notice_id: uuid.UUID) -> ApplicantNoticeRead | None:
    statement = (
        select(ApplicantNotification)
        .where(ApplicantNotification.id == notice_id)
        .options(
            selectinload(ApplicantNotification.candidate).selectinload(Candidate.snapshot),
            selectinload(ApplicantNotification.candidate)
            .selectinload(Candidate.version)
            .selectinload(JobVersion.job),
            selectinload(ApplicantNotification.job),
        )
    )
    row = await session.scalar(statement)
    if row is None:
        return None
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        await session.commit()
    notice = _to_read(row)
    return notice


def _batch_notice(row: ApplicantNotification, job: Job | None) -> ApplicantNoticeRead | None:
    summary = row.summary.strip()
    if job is None or not summary or is_practice_job(job.mail_subject):
        return None
    return ApplicantNoticeRead(
        id=row.id,
        candidate_id=None,
        job_id=job.id,
        full_name="",
        job_title=job.title,
        rank=None,
        message=summary,
        created_at=row.created_at,
        read=row.read_at is not None,
    )


def _to_read(row: ApplicantNotification) -> ApplicantNoticeRead | None:
    candidate = row.candidate
    if candidate is None:
        return _batch_notice(row, row.job)
    job = candidate.version.job if candidate.version is not None else None
    if job is not None and is_practice_job(job.mail_subject):
        return None
    rank = candidate.snapshot.rank if candidate.snapshot is not None else None
    title = job.title if job is not None else ""
    return ApplicantNoticeRead(
        id=row.id,
        candidate_id=candidate.id,
        full_name=candidate.full_name,
        job_title=title,
        rank=rank,
        message=notice_message(
            full_name=candidate.full_name,
            email=candidate.email,
            job_title=title,
            rank=rank,
        ),
        created_at=row.created_at,
        read=row.read_at is not None,
    )
