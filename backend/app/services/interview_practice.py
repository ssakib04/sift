import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.candidate import Candidate, InterviewSession, MagicLink
from app.models.job import Job, JobVersion
from app.services.interview_rules import InterviewError
from app.services.interview_sessions import OpenedSession, open_recruiter_session

PRACTICE_MAIL_SUBJECT = "sift-practice-interview"
PRACTICE_TITLE = "Practice interview"


def is_practice_job(mail_subject: str) -> bool:
    return mail_subject == PRACTICE_MAIL_SUBJECT


def practice_guest_url(public_app_url: str, token: str) -> str:
    """The link the other device opens. It does not require a recruiter sign-in."""
    base = public_app_url.strip().rstrip("/") or "http://localhost:3000"
    return f"{base}/invite/{token}"


async def open_practice_session(db: AsyncSession, settings: Settings, host: str) -> tuple[OpenedSession, str]:
    """Open a video room the recruiter can share without posting a job or emailing anyone."""
    version = await _practice_version(db)
    now = datetime.now(UTC)
    candidate_id = uuid.uuid4()
    token = secrets.token_urlsafe(32)
    candidate = Candidate(
        id=candidate_id,
        job_version_id=version.id,
        email=f"practice-{candidate_id.hex[:12]}@sift.invalid",
        full_name="Practice guest",
        content_sha256=secrets.token_hex(32),
        source_message_id=f"practice-{candidate_id.hex}",
        created_at=now,
    )
    db.add(candidate)
    db.add(MagicLink(id=uuid.uuid4(), candidate_id=candidate_id, token=token, created_at=now))
    db.add(
        InterviewSession(
            id=uuid.uuid4(),
            candidate_id=candidate_id,
            job_version_id=version.id,
            status="invited",
            created_at=now,
            processing_status="",
            copilot_explored=[],
            copilot_gaps=[],
            copilot_question="",
            copilot_turn_count=-1,
        )
    )
    await db.commit()
    opened = await open_recruiter_session(db, settings, candidate_id, host)
    if opened is None:
        raise InterviewError("INTERVIEW_UNAVAILABLE", "The practice room could not be opened.", 503)
    return opened, practice_guest_url(settings.public_app_url, token)


async def _practice_version(db: AsyncSession) -> JobVersion:
    job = await db.scalar(select(Job).where(Job.mail_subject == PRACTICE_MAIL_SUBJECT))
    if job is None:
        now = datetime.now(UTC)
        job = Job(id=uuid.uuid4(), title=PRACTICE_TITLE, mail_subject=PRACTICE_MAIL_SUBJECT, created_at=now)
        version = JobVersion(
            id=uuid.uuid4(),
            job_id=job.id,
            version_number=1,
            status="practice",
            seniority="",
            required_skills=[],
            preferred_skills=[],
            qualifications="",
            minimum_years=0,
            technical_weight=0,
            experience_weight=0,
            qualification_weight=0,
            contract="",
            category="",
            description="A private room for trying the interview video and transcript.",
            policy_excerpts=[],
            llm_tier="",
            fallback_used=False,
            created_at=now,
            locked_at=None,
        )
        job.versions.append(version)
        db.add(job)
        await db.flush()
        return version
    version = await db.scalar(select(JobVersion).where(JobVersion.job_id == job.id).order_by(JobVersion.version_number))
    if version is None:
        raise InterviewError("INTERVIEW_UNAVAILABLE", "The practice room could not be opened.", 503)
    return version
