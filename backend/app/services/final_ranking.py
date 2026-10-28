import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.graphs.master_assessment_graph import overall_from_parts, suitability_label
from app.models.candidate import Candidate, ConsolidatedAssessment, InterviewSession
from app.models.job import Job, JobVersion
from app.schemas.final_ranking import ApprovalBatchRead, ApprovalSkipRead, FinalRankRead, FinalRankingRead
from app.services.invites import InviteSender, letter_html


class FinalRankError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class FinishedPerson:
    candidate_id: uuid.UUID
    full_name: str
    email: str
    overall_score: float
    suitability_label: str
    cv_score: float | None
    interview_score: float | None
    quiz_score: int | None
    approval_mailed_at: datetime | None
    rank: int = 0


def pipeline_complete(
    *,
    cv_scored: bool,
    interview_ended: bool,
    overall_score: float | None,
) -> bool:
    """A final place requires CV screening, a finished interview, and a master score. The quiz stays separate."""
    return cv_scored and interview_ended and overall_score is not None


def order_finished(people: list[FinishedPerson]) -> list[FinishedPerson]:
    ordered = sorted(people, key=lambda person: (-person.overall_score, person.full_name.casefold(), str(person.candidate_id)))
    for index, person in enumerate(ordered, start=1):
        person.rank = index
    return ordered


def validate_approval_count(finished: int, count: int) -> None:
    if count < 1:
        raise FinalRankError("APPROVAL_COUNT", "Choose at least one person from the final ranking.")
    if finished == 0:
        raise FinalRankError(
            "APPROVAL_EMPTY",
            "Nobody has finished CV screening, the interview, and the assessment for this role.",
        )
    if count > finished:
        noun = "person has" if finished == 1 else "people have"
        raise FinalRankError("APPROVAL_COUNT", f"Only {finished} {noun} finished. Choose {finished} or fewer.")


def approval_body(*, candidate_name: str, job_title: str, company_name: str) -> str:
    who = candidate_name.strip() or "there"
    company = company_name.strip() or "our company"
    role = job_title.strip() or "the role"
    return (
        f"Dear {who},\n\n"
        f"Thank you for the time you gave us throughout the hiring process for {role} at {company}. "
        "We have completed our review of your CV, your video interview, and your written assessment.\n\n"
        "I am pleased to confirm that you have been approved to move forward for this role. "
        "We would like to continue with you, and a member of our hiring team will write again shortly with the next step.\n\n"
        f"Congratulations, and thank you again for your interest in joining {company}.\n\n"
        "Warm regards,\n"
        "The Hiring Team\n"
        f"{company}\n"
    )


def approval_html(*, candidate_name: str, job_title: str, company_name: str) -> str:
    who = candidate_name.strip() or "there"
    company = company_name.strip() or "our company"
    role = job_title.strip() or "the role"
    return letter_html(
        company_name=company,
        headline="Approval to proceed",
        greeting=f"Dear {who},",
        paragraphs=[
            (
                f"Thank you for the time you gave us throughout the hiring process for {role} at {company}. "
                "We have completed our review of your CV, your video interview, and your written assessment."
            ),
            (
                "I am pleased to confirm that you have been approved to move forward for this role. "
                "We would like to continue with you, and a member of our hiring team will write again shortly with the next step."
            ),
            f"Congratulations, and thank you again for your interest in joining {company}.",
        ],
        details=[("Role", role)],
        signoff=f"Warm regards,\nThe Hiring Team\n{company}",
    )


def mail_planned(
    ranked: list[FinishedPerson],
    count: int,
    sender: InviteSender,
    *,
    job_title: str,
    company_name: str,
    now: datetime,
) -> tuple[list[FinishedPerson], list[ApprovalSkipRead]]:
    """Mail the recruiter's chosen number of top finishers, skipping anyone already approved."""
    validate_approval_count(len(ranked), count)
    mailed: list[FinishedPerson] = []
    skipped: list[ApprovalSkipRead] = []
    for person in ranked[:count]:
        if person.approval_mailed_at is not None:
            skipped.append(ApprovalSkipRead(candidate_id=person.candidate_id, full_name=person.full_name, reason="already_mailed"))
            continue
        if not person.email.strip():
            skipped.append(ApprovalSkipRead(candidate_id=person.candidate_id, full_name=person.full_name, reason="missing_email"))
            continue
        try:
            sender.send(
                person.email.strip(),
                f"You are approved to proceed — {job_title}",
                approval_body(
                    candidate_name=person.full_name,
                    job_title=job_title,
                    company_name=company_name,
                ),
                html=approval_html(
                    candidate_name=person.full_name,
                    job_title=job_title,
                    company_name=company_name,
                ),
            )
        except Exception:
            skipped.append(ApprovalSkipRead(candidate_id=person.candidate_id, full_name=person.full_name, reason="mail_failed"))
            continue
        person.approval_mailed_at = now
        mailed.append(person)
    return mailed, skipped


def _person_from_candidate(candidate: Candidate) -> FinishedPerson | None:
    assessment = candidate.consolidated_assessment
    interview = candidate.interview_session
    quiz = candidate.quiz_attempt
    overall, suitability = _assessment_points(assessment)
    if not pipeline_complete(
        cv_scored=candidate.snapshot is not None,
        interview_ended=interview is not None and interview.status == "ended",
        overall_score=overall,
    ):
        return None
    assert overall is not None
    performance = interview.performance if interview is not None else None
    return FinishedPerson(
        candidate_id=candidate.id,
        full_name=candidate.full_name,
        email=candidate.email,
        overall_score=overall,
        suitability_label=suitability_label(suitability),
        cv_score=candidate.snapshot.aggregate_score if candidate.snapshot is not None else None,
        interview_score=performance.overall_score if performance is not None else None,
        quiz_score=quiz.score if quiz is not None else None,
        approval_mailed_at=candidate.approval_mailed_at,
    )


def _assessment_points(assessment: ConsolidatedAssessment | None) -> tuple[float | None, str]:
    if assessment is None:
        return None, "insufficient_evidence"
    scores = {item.component: item.score for item in assessment.component_scores}
    cv = scores.get("cv_screening")
    interview = scores.get("interview_qa")
    return overall_from_parts(
        float(cv) if isinstance(cv, int | float) else None,
        float(interview) if isinstance(interview, int | float) else None,
    )


def _read(person: FinishedPerson) -> FinalRankRead:
    return FinalRankRead(
        candidate_id=person.candidate_id,
        full_name=person.full_name,
        email=person.email,
        rank=person.rank,
        overall_score=person.overall_score,
        suitability_label=person.suitability_label,
        cv_score=person.cv_score,
        interview_score=person.interview_score,
        quiz_score=person.quiz_score,
        approval_mailed_at=person.approval_mailed_at,
    )


async def _locked_version(session: AsyncSession, job_id: uuid.UUID) -> tuple[Job, JobVersion | None]:
    job = await session.get(Job, job_id)
    if job is None:
        raise FinalRankError("JOB_NOT_FOUND", "That role could not be found.")
    version = await session.scalar(
        select(JobVersion)
        .where(JobVersion.job_id == job_id, JobVersion.status == "locked")
        .order_by(JobVersion.version_number.desc())
        .limit(1)
    )
    return job, version


async def _finished_people(session: AsyncSession, version_id: uuid.UUID) -> list[FinishedPerson]:
    statement = (
        select(Candidate)
        .where(Candidate.job_version_id == version_id)
        .options(
            selectinload(Candidate.snapshot),
            selectinload(Candidate.interview_session).selectinload(InterviewSession.performance),
            selectinload(Candidate.quiz_attempt),
            selectinload(Candidate.consolidated_assessment).selectinload(ConsolidatedAssessment.component_scores),
        )
    )
    candidates = list((await session.scalars(statement)).unique().all())
    finished = [person for candidate in candidates if (person := _person_from_candidate(candidate)) is not None]
    return order_finished(finished)


async def read_final_ranking(session: AsyncSession, job_id: uuid.UUID) -> FinalRankingRead:
    job, version = await _locked_version(session, job_id)
    rows = await _finished_people(session, version.id) if version is not None else []
    return FinalRankingRead(job_id=job.id, job_title=job.title, rows=[_read(person) for person in rows])


async def send_final_approvals(
    session: AsyncSession,
    settings: Settings,
    sender: InviteSender,
    job_id: uuid.UUID,
    count: int,
) -> ApprovalBatchRead:
    job, version = await _locked_version(session, job_id)
    ranked = await _finished_people(session, version.id) if version is not None else []
    now = datetime.now(UTC)
    mailed, skipped = mail_planned(
        ranked,
        count,
        sender,
        job_title=job.title,
        company_name=settings.company_name,
        now=now,
    )
    if mailed:
        found = {
            item.id: item
            for item in (
                await session.scalars(select(Candidate).where(Candidate.id.in_([person.candidate_id for person in mailed])))
            ).all()
        }
        for person in mailed:
            stored = found.get(person.candidate_id)
            if stored is not None:
                stored.approval_mailed_at = person.approval_mailed_at
    return ApprovalBatchRead(mailed=[_read(person) for person in mailed], skipped=skipped)
