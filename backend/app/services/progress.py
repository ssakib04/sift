import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.candidate import Candidate
from app.models.job import Job
from app.schemas.progress import ProgressBoardRead, ProgressCardRead, ProgressColumnRead, ProgressStage
from app.services.interview_practice import is_practice_job
from app.services.schedule import format_schedule, interview_zone

STAGE_ORDER: tuple[ProgressStage, ...] = (
    "received",
    "screened",
    "invited",
    "interview",
    "quiz",
    "assessed",
)

STAGE_LABELS: dict[ProgressStage, str] = {
    "received": "Received",
    "screened": "Screened",
    "invited": "Invited",
    "interview": "Interview",
    "quiz": "Quiz",
    "assessed": "Assessed",
}


@dataclass(frozen=True)
class ApplicantSignals:
    candidate_id: uuid.UUID
    full_name: str
    rank: int | None
    aggregate_score: float | None
    invited: bool
    interview_status: str | None
    quiz_submitted: bool
    quiz_score: int | None
    assessed: bool
    overall_score: float | None
    schedule_label: str = ""


def progress_stage(signals: ApplicantSignals) -> ProgressStage:
    """Place a person in the furthest stage already stored."""
    if signals.assessed:
        return "assessed"
    if signals.quiz_submitted:
        return "quiz"
    if signals.interview_status in {"started", "ended"}:
        return "interview"
    if signals.invited or signals.interview_status == "invited":
        return "invited"
    if signals.rank is not None and signals.aggregate_score is not None:
        return "screened"
    return "received"


def card_detail(signals: ApplicantSignals, stage: ProgressStage) -> str:
    if stage == "assessed" and signals.overall_score is not None:
        return f"Overall {signals.overall_score:.1f}"
    if stage == "quiz" and signals.quiz_score is not None:
        return f"Quiz {signals.quiz_score}"
    if stage == "interview":
        return "Interview ended" if signals.interview_status == "ended" else "Interview started"
    if stage == "invited":
        return signals.schedule_label or "Invite sent"
    if stage == "screened" and signals.rank is not None:
        return f"Rank #{signals.rank}"
    return "CV received"


def board_from_signals(job_id: uuid.UUID, job_title: str, applicants: list[ApplicantSignals]) -> ProgressBoardRead:
    grouped: dict[ProgressStage, list[ProgressCardRead]] = {stage: [] for stage in STAGE_ORDER}
    for signals in applicants:
        stage = progress_stage(signals)
        grouped[stage].append(
            ProgressCardRead(
                candidate_id=signals.candidate_id,
                full_name=signals.full_name or "Unnamed",
                rank=signals.rank,
                detail=card_detail(signals, stage),
                interview_status=signals.interview_status or "",
            )
        )
    for stage in STAGE_ORDER:
        grouped[stage].sort(key=lambda card: (card.rank is None, card.rank or 0, card.full_name.casefold()))
    return ProgressBoardRead(
        job_id=job_id,
        job_title=job_title,
        applicant_count=len(applicants),
        columns=[
            ProgressColumnRead(stage=stage, label=STAGE_LABELS[stage], cards=grouped[stage])
            for stage in STAGE_ORDER
        ],
    )


def role_on_board(mail_subject: str) -> bool:
    return not is_practice_job(mail_subject)


def signals_from_candidate(candidate: Candidate) -> ApplicantSignals:
    snapshot = candidate.snapshot
    quiz = candidate.quiz_attempt
    interview = candidate.interview_session
    assessment = candidate.consolidated_assessment
    quiz_submitted = quiz is not None and quiz.submitted_at is not None
    return ApplicantSignals(
        candidate_id=candidate.id,
        full_name=candidate.full_name,
        rank=snapshot.rank if snapshot is not None else None,
        aggregate_score=snapshot.aggregate_score if snapshot is not None else None,
        invited=candidate.magic_link is not None,
        interview_status=interview.status if interview is not None else None,
        quiz_submitted=quiz_submitted,
        quiz_score=quiz.score if quiz_submitted else None,
        assessed=assessment is not None,
        overall_score=assessment.overall_score if assessment is not None else None,
        schedule_label=format_schedule(
            interview.scheduled_start if interview is not None else None,
            interview.scheduled_end if interview is not None else None,
            interview_zone(get_settings().interview_timezone),
        ),
    )


async def list_progress(session: AsyncSession) -> list[ProgressBoardRead]:
    jobs = list((await session.scalars(select(Job).order_by(Job.title))).unique().all())
    statement = select(Candidate).options(
        selectinload(Candidate.snapshot),
        selectinload(Candidate.magic_link),
        selectinload(Candidate.interview_session),
        selectinload(Candidate.quiz_attempt),
        selectinload(Candidate.consolidated_assessment),
        selectinload(Candidate.version),
    )
    candidates = list((await session.scalars(statement)).unique().all())
    buckets: dict[uuid.UUID, list[ApplicantSignals]] = {}
    for candidate in candidates:
        if candidate.version is None:
            continue
        buckets.setdefault(candidate.version.job_id, []).append(signals_from_candidate(candidate))
    boards = [
        board_from_signals(job.id, job.title, buckets.get(job.id, []))
        for job in jobs
        if role_on_board(job.mail_subject)
    ]
    boards.sort(key=lambda board: board.job_title.casefold())
    return boards
