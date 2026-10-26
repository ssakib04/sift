import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate, InterviewSession
from app.models.job import JobVersion
from app.schemas.interviews import RoleInterviewsRead, ScheduledInterviewRead
from app.services.schedule import format_schedule, interview_zone

_STATUS_LABELS = {
    "invited": "Scheduled",
    "started": "In progress",
    "ended": "Ended",
}


@dataclass(frozen=True)
class AgendaRow:
    session_id: uuid.UUID
    candidate_id: uuid.UUID
    full_name: str
    job_id: uuid.UUID
    job_title: str
    status: str
    scheduled_start: datetime
    schedule_label: str


def interview_status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, status.replace("_", " ").strip().title() or "Scheduled")


def group_scheduled_interviews(rows: list[AgendaRow]) -> list[RoleInterviewsRead]:
    """Group scheduled calls by role. A role with no scheduled interview is omitted."""
    buckets: dict[uuid.UUID, list[AgendaRow]] = {}
    titles: dict[uuid.UUID, str] = {}
    for row in rows:
        buckets.setdefault(row.job_id, []).append(row)
        titles[row.job_id] = row.job_title
    roles: list[RoleInterviewsRead] = []
    for job_id, items in buckets.items():
        ordered = sorted(items, key=lambda item: (item.scheduled_start, item.full_name.casefold()))
        roles.append(
            RoleInterviewsRead(
                job_id=job_id,
                job_title=titles[job_id],
                interviews=[
                    ScheduledInterviewRead(
                        session_id=item.session_id,
                        candidate_id=item.candidate_id,
                        full_name=item.full_name.strip() or "Unnamed",
                        status=interview_status_label(item.status),
                        schedule_label=item.schedule_label,
                        scheduled_start=item.scheduled_start,
                    )
                    for item in ordered
                ],
            )
        )
    roles.sort(key=lambda role: (role.interviews[0].scheduled_start, role.job_title.casefold()))
    return roles


async def list_scheduled_interviews(session: AsyncSession, *, zone_name: str) -> list[RoleInterviewsRead]:
    from app.services.interview_practice import is_practice_job

    zone = interview_zone(zone_name)
    statement = (
        select(InterviewSession)
        .where(
            InterviewSession.scheduled_start.is_not(None),
            InterviewSession.scheduled_end.is_not(None),
        )
        .options(
            selectinload(InterviewSession.candidate).selectinload(Candidate.version).selectinload(JobVersion.job)
        )
        .order_by(InterviewSession.scheduled_start)
    )
    stored = list((await session.scalars(statement)).unique().all())
    rows: list[AgendaRow] = []
    for interview in stored:
        candidate = interview.candidate
        if candidate is None or candidate.version is None or candidate.version.job is None:
            continue
        job = candidate.version.job
        if is_practice_job(job.mail_subject):
            continue
        start = interview.scheduled_start
        end = interview.scheduled_end
        if start is None or end is None:
            continue
        rows.append(
            AgendaRow(
                session_id=interview.id,
                candidate_id=candidate.id,
                full_name=candidate.full_name,
                job_id=job.id,
                job_title=job.title,
                status=interview.status,
                scheduled_start=start,
                schedule_label=format_schedule(start, end, zone),
            )
        )
    return group_scheduled_interviews(rows)
