"""Assess how an interview was run. The candidate's suitability is not an input."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import (
    Candidate,
    InterviewAnalysis,
    InterviewQuality,
    InterviewQualityDimension,
    InterviewQualityRecommendation,
    InterviewSession,
    QAPair,
    TranscriptSegment,
)
from app.models.job import JobChecklistQuery
from app.schemas.interview_quality import InterviewQualityRead, QualityDimensionRead, QualityRecommendationRead
from app.services.interview_score import question_covered
from app.services.transcript_cleanup import is_disfluency_only, pair_speech, recruiter_aside, same_line, substantive

DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("question_effectiveness", "Question effectiveness"),
    ("competency_coverage", "Competency coverage"),
    ("process_consistency", "Consistency across candidates"),
    ("interaction_quality", "Interaction quality"),
)
_TOKEN = re.compile(r"[A-Za-z0-9+#]+(?:[./-][A-Za-z0-9+#]+)*")
_AUDIO_CHECK = re.compile(r"\b(hear me|audible|microphone|connection)\b", re.IGNORECASE)
_STOP = {
    "a",
    "an",
    "the",
    "of",
    "and",
    "or",
    "with",
    "in",
    "for",
    "to",
    "on",
    "at",
    "by",
    "from",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "this",
    "that",
    "have",
    "has",
    "had",
    "your",
    "you",
    "they",
    "their",
    "them",
    "what",
    "when",
    "where",
    "which",
    "who",
    "how",
    "did",
    "does",
    "about",
    "into",
    "over",
    "than",
    "then",
    "first",
}
_SIGNAL_WORDS = 8
_SIGNAL_SCORE = 4.0
_LIMITS = {"unexplored": 8, "low_signal": 6, "consistency": 6, "speaking": 1}


class QualityError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class QualityTurn:
    speaker: str
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ChecklistTopic:
    query_id: str
    question: str


@dataclass(frozen=True)
class AnsweredQuestion:
    question: str
    answer: str
    relevance: float | None = None
    completeness: float | None = None
    query_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualityDimension:
    key: str
    label: str
    score: float | None
    note: str


@dataclass(frozen=True)
class QualityRecommendation:
    kind: str
    text: str


@dataclass(frozen=True)
class QualityDraft:
    """Process review only. Candidate suitability does not read this draft."""

    overall_score: float
    summary: str
    interviewer_share: float
    candidate_share: float
    dimensions: list[QualityDimension]
    recommendations: list[QualityRecommendation]


def assess_interview(
    turns: list[QualityTurn],
    checklist: list[ChecklistTopic],
    pairs: list[AnsweredQuestion] | None = None,
    peer_coverage: list[set[str]] | None = None,
) -> QualityDraft:
    """Review the interview process and recommend what to change next time."""
    speech = _candidate_text(turns)
    asked = [
        item
        for item in (pairs if pairs else _questions_from_turns(turns))
        if not _audio_check(item.question) and _reportable(item, checklist)
    ]
    interviewer_share, candidate_share = _shares(turns)
    covered = _covered_ids(checklist, speech, asked)
    questions, low_signal = _question_review(asked)
    coverage, unexplored = _coverage_review(checklist, covered)
    consistency, missed = _consistency_review(checklist, covered, peer_coverage or [])
    interaction, speaking = _interaction_review(turns, interviewer_share, candidate_share, len(asked))
    dimensions = [
        QualityDimension("question_effectiveness", "Question effectiveness", questions[0], questions[1]),
        QualityDimension("competency_coverage", "Competency coverage", coverage[0], coverage[1]),
        QualityDimension("process_consistency", "Consistency across candidates", consistency[0], consistency[1]),
        QualityDimension("interaction_quality", "Interaction quality", interaction[0], interaction[1]),
    ]
    recommendations = _recommendations(unexplored, low_signal, missed, speaking)
    scored = [item.score for item in dimensions if item.score is not None]
    overall = round(sum(scored) / len(scored), 1) if scored else 0.0
    return QualityDraft(
        overall_score=overall,
        summary=f"Interview process quality is {overall:.1f} out of 100. This report is about how the interview was run.",
        interviewer_share=interviewer_share,
        candidate_share=candidate_share,
        dimensions=dimensions,
        recommendations=recommendations,
    )


async def read_interview_quality(db: AsyncSession, candidate_id: uuid.UUID) -> InterviewQualityRead:
    interview = await _ended_interview(db, candidate_id)
    stored = await _load(db, interview.id)
    if stored is None:
        raise QualityError("INTERVIEW_QUALITY_NOT_FOUND", "The interview process has not been reviewed yet.", 404)
    return _to_read(candidate_id, stored)


async def build_interview_quality(db: AsyncSession, candidate_id: uuid.UUID) -> InterviewQualityRead:
    interview = await _ended_interview(db, candidate_id)
    stored = await _load(db, interview.id)
    if stored is not None:
        return _to_read(candidate_id, stored)
    await store_interview_quality(db, interview)
    await db.commit()
    saved = await _load(db, interview.id)
    if saved is None:
        raise QualityError("INTERVIEW_QUALITY_EMPTY", "The interview review could not be saved.", 409)
    return _to_read(candidate_id, saved)


async def store_interview_quality(db: AsyncSession, interview: InterviewSession) -> None:
    existing = await db.scalar(select(InterviewQuality.id).where(InterviewQuality.session_id == interview.id))
    if existing is not None:
        return
    checklist = await _checklist(db, interview.job_version_id)
    segments = await _segments(db, interview.id)
    turns = [
        QualityTurn(segment.speaker, segment.start_time, segment.end_time, segment.text)
        for segment in segments
        if segment.text.strip()
    ]
    pairs = await _stored_pairs(db, interview.id)
    peers = await _peer_coverage(db, interview, checklist)
    draft = assess_interview(turns, checklist, pairs, peers)
    quality = InterviewQuality(
        id=uuid.uuid4(),
        session_id=interview.id,
        overall_score=draft.overall_score,
        summary=draft.summary,
        interviewer_share=draft.interviewer_share,
        candidate_share=draft.candidate_share,
        created_at=datetime.now(UTC),
    )
    db.add(quality)
    await db.flush()
    for sequence, item in enumerate(draft.dimensions, start=1):
        db.add(
            InterviewQualityDimension(
                id=uuid.uuid4(),
                quality_id=quality.id,
                dimension_key=item.key,
                label=item.label,
                score=item.score,
                note=item.note,
                sequence=sequence,
            )
        )
    for sequence, item in enumerate(draft.recommendations, start=1):
        db.add(
            InterviewQualityRecommendation(
                id=uuid.uuid4(),
                quality_id=quality.id,
                sequence=sequence,
                kind=item.kind,
                text=item.text,
            )
        )


def _question_review(asked: list[AnsweredQuestion]) -> tuple[tuple[float, str], list[str]]:
    if not asked:
        return (0.0, "The interviewer asked no questions."), []
    useful = [item for item in asked if _has_signal(item)]
    weak = [item.question for item in asked if not _has_signal(item) and item.question.strip()]
    score = _points(100 * len(useful) / len(asked))
    return (score, f"{len(useful)} of {len(asked)} questions produced a usable answer."), weak


def _coverage_review(
    checklist: list[ChecklistTopic],
    covered: set[str],
) -> tuple[tuple[float | None, str], list[ChecklistTopic]]:
    if not checklist:
        return (None, "This role has no checklist to compare with the interview."), []
    reached = [item for item in checklist if item.query_id in covered]
    missed = [item for item in checklist if item.query_id not in covered]
    score = _points(100 * len(reached) / len(checklist))
    return (score, f"The interview reached {len(reached)} of {len(checklist)} required competencies."), missed


def _consistency_review(
    checklist: list[ChecklistTopic],
    covered: set[str],
    peers: list[set[str]],
) -> tuple[tuple[float | None, str], list[ChecklistTopic]]:
    if not peers:
        return (None, "No other finished interview for this role yet, so consistency is not compared."), []
    need = 1 if len(peers) == 1 else (len(peers) + 1) // 2
    common = [item for item in checklist if sum(1 for peer in peers if item.query_id in peer) >= need]
    if not common:
        return (None, "Other interviews for this role do not share a competency pattern yet."), []
    missed = [item for item in common if item.query_id not in covered]
    score = _points(100 * (len(common) - len(missed)) / len(common))
    return (
        score,
        f"This interview covered {len(common) - len(missed)} of {len(common)} competencies that other interviews for this role covered.",
    ), missed


def _interaction_review(
    turns: list[QualityTurn],
    interviewer_share: float,
    candidate_share: float,
    questions: int,
) -> tuple[tuple[float, str], str]:
    if not any(turn.text.strip() for turn in turns):
        return (0.0, "No speech was captured."), "No speech was captured, so speaking time cannot be compared."
    balance = _balance(candidate_share)
    exchange = _points(min(100.0, 100 * questions / 4))
    score = _points(0.7 * balance + 0.3 * exchange)
    note = (
        f"The interviewer spoke for {round(interviewer_share * 100)}% of the interview and the candidate spoke for "
        f"{round(candidate_share * 100)}%."
    )
    speaking = ""
    if interviewer_share >= 0.55:
        speaking = (
            f"The interviewer spoke for {round(interviewer_share * 100)}% of the interview. "
            "Leave more time for the candidate."
        )
    elif candidate_share >= 0.9:
        speaking = (
            f"The candidate spoke for {round(candidate_share * 100)}% of the interview. "
            "Ask more of the planned questions."
        )
    return (score, note), speaking


def _recommendations(
    unexplored: list[ChecklistTopic],
    low_signal: list[str],
    missed: list[ChecklistTopic],
    speaking: str,
) -> list[QualityRecommendation]:
    items: list[QualityRecommendation] = []
    for topic in unexplored[: _LIMITS["unexplored"]]:
        items.append(QualityRecommendation("unexplored", f"This interview never reached: {_clip(topic.question)}"))
    for question in low_signal[: _LIMITS["low_signal"]]:
        items.append(
            QualityRecommendation(
                "low_signal",
                f'The question "{_clip(question)}" produced little signal. Ask it in a way that invites a specific example.',
            )
        )
    for topic in missed[: _LIMITS["consistency"]]:
        items.append(
            QualityRecommendation(
                "consistency",
                f"Other interviews for this role covered this requirement: {_clip(topic.question)}",
            )
        )
    if speaking:
        items.append(QualityRecommendation("speaking", speaking))
    return items


def _covered_ids(checklist: list[ChecklistTopic], speech: str, asked: list[AnsweredQuestion]) -> set[str]:
    linked = {query_id for item in asked for query_id in item.query_ids}
    return {item.query_id for item in checklist if item.query_id in linked or _covered(item.question, speech)}


def _questions_from_turns(turns: list[QualityTurn]) -> list[AnsweredQuestion]:
    sequenced = [(turn.speaker, turn.text, turn.start, turn.end) for turn in turns]
    return [
        AnsweredQuestion(item.question, item.answer)
        for item in pair_speech(sequenced)
        if item.question.strip()
    ]


def _audio_check(question: str) -> bool:
    return len(_tokens(question)) <= 12 and _AUDIO_CHECK.search(question) is not None


def _has_signal(item: AnsweredQuestion) -> bool:
    if len(_tokens(item.answer)) < _SIGNAL_WORDS:
        return False
    scores = [score for score in (item.relevance, item.completeness) if score is not None]
    if not scores:
        return True
    return sum(scores) / len(scores) >= _SIGNAL_SCORE


def _shares(turns: list[QualityTurn]) -> tuple[float, float]:
    timed = any(max(0.0, turn.end - turn.start) > 0 for turn in turns if turn.text.strip())

    def weight(turn: QualityTurn) -> float:
        if not turn.text.strip() or turn.speaker not in {"recruiter", "candidate"}:
            return 0.0
        if timed:
            return max(0.0, turn.end - turn.start)
        return float(len(_tokens(turn.text)))

    interviewer = sum(weight(turn) for turn in turns if turn.speaker == "recruiter")
    candidate = sum(weight(turn) for turn in turns if turn.speaker == "candidate")
    total = interviewer + candidate
    if total <= 0:
        return 0.0, 0.0
    return round(interviewer / total, 3), round(candidate / total, 3)


def _balance(candidate_share: float) -> float:
    if 0.55 <= candidate_share <= 0.75:
        return 100.0
    if candidate_share < 0.55:
        return _points(100 * candidate_share / 0.55)
    return _points(100 * (1 - candidate_share) / 0.25)


def _reportable(item: AnsweredQuestion, checklist: list[ChecklistTopic]) -> bool:
    if item.answer.strip():
        return True
    return any(question_covered(topic.question, item.question) for topic in checklist)


def _covered(question: str, speech: str) -> bool:
    return question_covered(question, speech)


def _candidate_text(turns: list[QualityTurn]) -> str:
    parts: list[str] = []
    last_prompt = ""
    for turn in turns:
        if turn.speaker == "recruiter":
            if not recruiter_aside(turn.text):
                last_prompt = turn.text
            continue
        if turn.speaker != "candidate" or is_disfluency_only(turn.text) or same_line(turn.text, last_prompt):
            continue
        spoken = substantive(turn.text)
        if spoken:
            parts.append(spoken)
    return " ".join(parts).strip()


def _tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN.finditer(text)]


def _content(text: str) -> list[str]:
    return [token for token in _tokens(text) if len(token) >= 4 and token not in _STOP]


def _points(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _clip(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= 180:
        return cleaned
    return cleaned[:177].rstrip() + "..."


async def _ended_interview(db: AsyncSession, candidate_id: uuid.UUID) -> InterviewSession:
    if await db.get(Candidate, candidate_id) is None:
        raise QualityError("CANDIDATE_NOT_FOUND", "Candidate not found.", 404)
    interview = await db.scalar(select(InterviewSession).where(InterviewSession.candidate_id == candidate_id))
    if interview is None or interview.status != "ended":
        raise QualityError("INTERVIEW_NOT_ENDED", "Interview quality is reviewed after the interview ends.", 409)
    return interview


async def _checklist(db: AsyncSession, version_id: uuid.UUID) -> list[ChecklistTopic]:
    rows = list((await db.scalars(select(JobChecklistQuery).where(JobChecklistQuery.version_id == version_id))).all())
    rows.sort(key=lambda query: int(query.query_id[1:]) if query.query_id[1:].isdigit() else 0)
    return [ChecklistTopic(query.query_id, query.question) for query in rows]


async def _segments(db: AsyncSession, session_id: uuid.UUID) -> list[TranscriptSegment]:
    result = await db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.start_time, TranscriptSegment.created_at)
    )
    return list(result.all())


async def _stored_pairs(db: AsyncSession, session_id: uuid.UUID) -> list[AnsweredQuestion]:
    analysis = await db.scalar(
        select(InterviewAnalysis)
        .where(InterviewAnalysis.session_id == session_id)
        .options(selectinload(InterviewAnalysis.pairs))
    )
    if analysis is None:
        return []
    ordered = sorted(analysis.pairs, key=lambda pair: pair.sequence)
    return [_pair(pair) for pair in ordered if pair.question.strip()]


def _pair(pair: QAPair) -> AnsweredQuestion:
    query_ids = tuple(str(item) for item in (pair.query_ids or []) if str(item).strip())
    return AnsweredQuestion(
        question=pair.question,
        answer=pair.answer,
        relevance=pair.relevance,
        completeness=pair.completeness,
        query_ids=query_ids,
    )


async def _peer_coverage(
    db: AsyncSession,
    interview: InterviewSession,
    checklist: list[ChecklistTopic],
) -> list[set[str]]:
    peers = list(
        (
            await db.scalars(
                select(InterviewSession).where(
                    InterviewSession.job_version_id == interview.job_version_id,
                    InterviewSession.status == "ended",
                    InterviewSession.id != interview.id,
                )
            )
        ).all()
    )
    covered: list[set[str]] = []
    for peer in peers:
        segments = await _segments(db, peer.id)
        speech = " ".join(segment.text.strip() for segment in segments if segment.speaker == "candidate" and segment.text.strip())
        pairs = await _stored_pairs(db, peer.id)
        covered.append(_covered_ids(checklist, speech, pairs))
    return covered


async def _load(db: AsyncSession, session_id: uuid.UUID) -> InterviewQuality | None:
    return await db.scalar(
        select(InterviewQuality)
        .where(InterviewQuality.session_id == session_id)
        .options(
            selectinload(InterviewQuality.dimensions),
            selectinload(InterviewQuality.recommendations),
        )
    )


def _to_read(candidate_id: uuid.UUID, quality: InterviewQuality) -> InterviewQualityRead:
    dimensions = sorted(quality.dimensions, key=lambda item: item.sequence)
    recommendations = sorted(quality.recommendations, key=lambda item: item.sequence)
    return InterviewQualityRead(
        candidate_id=candidate_id,
        overall_score=quality.overall_score,
        summary=quality.summary,
        interviewer_share=quality.interviewer_share,
        candidate_share=quality.candidate_share,
        dimensions=[
            QualityDimensionRead(key=item.dimension_key, label=item.label, score=item.score, note=item.note)
            for item in dimensions
        ],
        recommendations=[QualityRecommendationRead(kind=item.kind, text=item.text) for item in recommendations],
    )
