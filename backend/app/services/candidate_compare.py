import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.llm_fallback import FallbackLLMManager, LLMFallbackExhaustedError
from app.graphs.job_creation_graph import JobGraphError, parse_json_object
from app.graphs.master_assessment_graph import suitability_label
from app.models.candidate import (
    Candidate,
    ConsolidatedAssessment,
    InterviewPerformance,
    InterviewSession,
    McqAttempt,
    ScoreSnapshot,
)
from app.models.job import JobVersion
from app.schemas.compare import CandidateCompareRead, CompareNarrative, CompareSide

COMPARE_SYSTEM = (
    "You compare two applicants for the same role. Use only the facts in the prompt. "
    "Return a JSON object with keys summary, left_edge, right_edge, and tradeoff. "
    "Each value is one or two sentences and names both people in the summary. "
    "left_edge says where the first person is stronger. right_edge says where the second person is stronger. "
    "tradeoff is the practical choice between them. "
    "Do not invent scores, quotes, employers, or skills. "
    "If a fact says not scored, say it is not scored and do not supply a number. "
    "Do not mention any number that is not written in the facts."
)

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_LOAD = (
    selectinload(Candidate.snapshot),
    selectinload(Candidate.quiz_attempt),
    selectinload(Candidate.interview_session)
    .selectinload(InterviewSession.performance)
    .selectinload(InterviewPerformance.dimensions),
    selectinload(Candidate.consolidated_assessment).selectinload(ConsolidatedAssessment.strengths),
    selectinload(Candidate.consolidated_assessment).selectinload(ConsolidatedAssessment.weaknesses),
    selectinload(Candidate.version).selectinload(JobVersion.job),
)


class CompareError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class CompareFacts:
    candidate_id: uuid.UUID
    full_name: str
    job_id: uuid.UUID
    job_title: str
    rank: int | None
    cv_score: float | None
    technical_score: float | None
    experience_score: float | None
    qualification_score: float | None
    mcq_score: int | None
    interview_score: float | None
    interview_note: str
    overall_score: float | None
    suitability_label: str
    strengths: tuple[str, ...]
    gaps: tuple[str, ...]


def pair_error(left: CompareFacts, right: CompareFacts) -> CompareError | None:
    if left.candidate_id == right.candidate_id:
        return CompareError("COMPARE_SAME_PERSON", "Choose two different candidates.", 400)
    if left.job_id != right.job_id:
        return CompareError(
            "COMPARE_DIFFERENT_ROLES",
            "Choose two candidates who applied for the same role.",
            400,
        )
    return None


def profile_from_candidate(candidate: Candidate) -> CompareFacts:
    version = candidate.version
    job = version.job if version is not None else None
    if version is None or job is None:
        raise CompareError("CANDIDATE_NOT_FOUND", "One of those candidates is not on file.", 404)
    interview_score, interview_note = _interview(candidate)
    assessment = candidate.consolidated_assessment
    strengths: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    overall: float | None = None
    label = ""
    if assessment is not None:
        overall = assessment.overall_score
        label = suitability_label(assessment.overall_suitability)
        strengths = tuple(
            item.text.strip()
            for item in sorted(assessment.strengths, key=lambda item: item.sequence)
            if item.text.strip()
        )
        gaps = tuple(
            item.text.strip()
            for item in sorted(assessment.weaknesses, key=lambda item: item.sequence)
            if item.text.strip()
        )
    snapshot = candidate.snapshot
    return CompareFacts(
        candidate_id=candidate.id,
        full_name=candidate.full_name.strip() or "Unnamed",
        job_id=job.id,
        job_title=job.title.strip() or "Role",
        rank=snapshot.rank if snapshot is not None else None,
        cv_score=snapshot.aggregate_score if snapshot is not None else None,
        technical_score=snapshot.technical_score if snapshot is not None else None,
        experience_score=snapshot.experience_score if snapshot is not None else None,
        qualification_score=snapshot.qualification_score if snapshot is not None else None,
        mcq_score=_quiz_score(candidate.quiz_attempt),
        interview_score=interview_score,
        interview_note=interview_note,
        overall_score=overall,
        suitability_label=label,
        strengths=strengths,
        gaps=gaps,
    )


def facts_brief(left: CompareFacts, right: CompareFacts) -> str:
    return "\n".join(
        [
            f"Role: {left.job_title}",
            _person_block("Left", left),
            _person_block("Right", right),
        ]
    )


def narrative_from_scores(left: CompareFacts, right: CompareFacts) -> CompareNarrative:
    lead, measure = _lead(left, right)
    if lead is None:
        summary = (
            f"{left.full_name} and {right.full_name} do not both have a {measure} on {left.job_title} yet. "
            f"{left.full_name}: {_available(left)}. {right.full_name}: {_available(right)}."
        )
    elif lead[0] == "level":
        summary = (
            f"{left.full_name} and {right.full_name} are level on {measure} for {left.job_title}. "
            f"{_score_line(left, measure)} {_score_line(right, measure)}"
        )
    else:
        ahead, behind = lead
        summary = (
            f"{ahead.full_name} is ahead of {behind.full_name} on {measure} for {ahead.job_title}. "
            f"{_score_line(ahead, measure)} {_score_line(behind, measure)}"
        )
    return CompareNarrative(
        summary=_clip(summary),
        left_edge=_clip(_edge(left)),
        right_edge=_clip(_edge(right)),
        tradeoff=_clip(_tradeoff(left, right)),
        source="scores",
    )


def narrative_from_model(text: str, left: CompareFacts, right: CompareFacts) -> CompareNarrative | None:
    try:
        payload = parse_json_object(text)
    except JobGraphError:
        return None
    brief = facts_brief(left, right)
    try:
        narrative = CompareNarrative(
            summary=_clean(payload.get("summary")),
            left_edge=_clean(payload.get("left_edge")),
            right_edge=_clean(payload.get("right_edge")),
            tradeoff=_clean(payload.get("tradeoff")),
            source="model",
        )
    except ValueError:
        return None
    joined = " ".join([narrative.summary, narrative.left_edge, narrative.right_edge, narrative.tradeoff])
    if left.full_name not in joined or right.full_name not in joined:
        return None
    if not _grounded(joined, brief):
        return None
    return narrative


async def write_comparison(
    llm: FallbackLLMManager,
    left: CompareFacts,
    right: CompareFacts,
) -> CompareNarrative:
    brief = facts_brief(left, right)
    try:
        response = await llm.complete(
            f"Compare these two applicants using only these facts.\n\n{brief}",
            system=COMPARE_SYSTEM,
        )
    except LLMFallbackExhaustedError:
        return narrative_from_scores(left, right)
    parsed = narrative_from_model(response.content, left, right)
    if parsed is None:
        return narrative_from_scores(left, right)
    return parsed


async def compare_candidates(
    db: AsyncSession,
    llm: FallbackLLMManager,
    left_id: uuid.UUID,
    right_id: uuid.UUID,
) -> CandidateCompareRead:
    left_row = await _load(db, left_id)
    right_row = await _load(db, right_id)
    if left_row is None or right_row is None:
        raise CompareError("CANDIDATE_NOT_FOUND", "One of those candidates is not on file.", 404)
    left = profile_from_candidate(left_row)
    right = profile_from_candidate(right_row)
    problem = pair_error(left, right)
    if problem is not None:
        raise problem
    narrative = await write_comparison(llm, left, right)
    return CandidateCompareRead(
        job_id=left.job_id,
        job_title=left.job_title,
        left=_side(left),
        right=_side(right),
        summary=narrative.summary,
        left_edge=narrative.left_edge,
        right_edge=narrative.right_edge,
        tradeoff=narrative.tradeoff,
        source=narrative.source,
    )


async def _load(db: AsyncSession, candidate_id: uuid.UUID) -> Candidate | None:
    return await db.scalar(select(Candidate).where(Candidate.id == candidate_id).options(*_LOAD))


def _side(facts: CompareFacts) -> CompareSide:
    return CompareSide(
        candidate_id=facts.candidate_id,
        full_name=facts.full_name,
        rank=facts.rank,
        cv_score=facts.cv_score,
        technical_score=facts.technical_score,
        experience_score=facts.experience_score,
        qualification_score=facts.qualification_score,
        mcq_score=facts.mcq_score,
        interview_score=facts.interview_score,
        interview_note=facts.interview_note,
        overall_score=facts.overall_score,
        suitability_label=facts.suitability_label,
        strengths=list(facts.strengths),
        gaps=list(facts.gaps),
    )


def _person_block(label: str, facts: CompareFacts) -> str:
    strengths = "; ".join(facts.strengths) or "none recorded"
    gaps = "; ".join(facts.gaps) or "none recorded"
    note = facts.interview_note or "none"
    rank = str(facts.rank) if facts.rank is not None else "not ranked"
    suitability = facts.suitability_label or "not assessed"
    return "\n".join(
        [
            f"{label}: {facts.full_name}",
            f"Rank: {rank}",
            f"CV aggregate (0 to 1): {_shown(facts.cv_score, 2)}",
            f"CV technical (0 to 1): {_shown(facts.technical_score, 2)}",
            f"CV experience (0 to 1): {_shown(facts.experience_score, 2)}",
            f"CV qualification (0 to 1): {_shown(facts.qualification_score, 2)}",
            f"Interview (0 to 100): {_shown(facts.interview_score, 1)}",
            f"Interview note: {note}",
            f"Master score (0 to 100): {_shown(facts.overall_score, 1)}",
            f"Suitability: {suitability}",
            f"Strengths: {strengths}",
            f"Gaps: {gaps}",
        ]
    )


def _shown(value: float | None, digits: int) -> str:
    if value is None:
        return "not scored"
    return f"{value:.{digits}f}"


def _quiz_score(attempt: McqAttempt | None) -> int | None:
    if attempt is None or attempt.submitted_at is None or attempt.score is None:
        return None
    return attempt.score


def _interview(candidate: Candidate) -> tuple[float | None, str]:
    session = candidate.interview_session
    performance = session.performance if session is not None else None
    if performance is None:
        return None, ""
    note = " ".join(performance.summary.split())
    if not note:
        for dimension in sorted(performance.dimensions, key=lambda item: item.sequence):
            evidence = " ".join(dimension.evidence.split())
            if evidence:
                note = evidence
                break
    return performance.overall_score, note[:400]


def _lead(left: CompareFacts, right: CompareFacts) -> tuple[tuple[CompareFacts, CompareFacts] | tuple[str] | None, str]:
    for measure, left_value, right_value in (
        ("the master score", left.overall_score, right.overall_score),
        ("the CV score", left.cv_score, right.cv_score),
    ):
        if left_value is None or right_value is None:
            continue
        if left_value == right_value:
            return ("level",), measure
        if left_value > right_value:
            return (left, right), measure
        return (right, left), measure
    return None, "master score or CV score"


def _score_line(facts: CompareFacts, measure: str) -> str:
    if measure == "the master score":
        return f"{facts.full_name} {_shown(facts.overall_score, 1)}."
    return f"{facts.full_name} {_shown(facts.cv_score, 2)}."


def _clip(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= 800:
        return cleaned
    return cleaned[:797].rstrip() + "..."


def _available(facts: CompareFacts) -> str:
    parts = [
        f"CV {_shown(facts.cv_score, 2)}",
        f"interview {_shown(facts.interview_score, 1)}",
        f"master {_shown(facts.overall_score, 1)}",
    ]
    return ", ".join(parts)


def _edge(facts: CompareFacts) -> str:
    if facts.strengths:
        return f"{facts.full_name}: {facts.strengths[0]}"
    if facts.interview_note:
        return f"{facts.full_name} said: {facts.interview_note}"
    if facts.cv_score is not None:
        return f"{facts.full_name} has a CV score of {_shown(facts.cv_score, 2)}."
    return f"{facts.full_name} has no scored edge yet."


def _tradeoff(left: CompareFacts, right: CompareFacts) -> str:
    left_gap = left.gaps[0] if left.gaps else "no recorded gap"
    right_gap = right.gaps[0] if right.gaps else "no recorded gap"
    return f"{left.full_name}: {left_gap}. {right.full_name}: {right_gap}."


def _clean(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("comparison field")
    text = " ".join(value.split())
    if not text:
        raise ValueError("comparison field")
    return text


def _grounded(narrative: str, brief: str) -> bool:
    return _numbers(narrative) <= _numbers(brief)


def _numbers(text: str) -> set[str]:
    found: set[str] = set()
    for token in _NUMBER.findall(text):
        if "." in token:
            token = token.rstrip("0").rstrip(".")
        found.add(token)
    return found
