"""Score an interview on its own. The CV score is never an input."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import desc, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.llm_fallback import FallbackLLMManager, LLMFallbackExhaustedError
from app.graphs.job_creation_graph import JobGraphError, parse_json_object
from app.models.candidate import (
    Candidate,
    InterviewAnalysis,
    InterviewPerformance,
    InterviewPerformanceDimension,
    InterviewSession,
    TranscriptSegment,
)
from app.models.job import JobChecklistQuery, JobVersion
from app.schemas.interview_score import InterviewHistoryRead, InterviewScoreRead, PerformanceDimensionRead
from app.services.cv_claims import anchored_quote

DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("technical_competency", "Technical competency"),
    ("communication", "Communication"),
    ("relevance", "Relevance of responses"),
    ("problem_solving", "Problem-solving approach"),
    ("experience_depth", "Depth of experience"),
    ("job_alignment", "Alignment with job requirements"),
)
_TOKEN = re.compile(r"[A-Za-z0-9+#]+(?:[./-][A-Za-z0-9+#]+)*")
_SENTENCE = re.compile(r"[^.!?]+(?:[.!?]|$)")
_EXAMPLE = re.compile(
    r"\b(for example|when i|i built|i led|i shipped|i designed|i implemented)\b",
    re.IGNORECASE,
)
_DIGIT = re.compile(r"\d")
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
_MECHANISM = {"implemented", "designed", "built", "using", "service", "database", "query", "model", "tested", "api"}
_PROBLEM = {
    "cause": {"because", "cause", "root"},
    "sequence": {"first", "then", "next", "step", "finally"},
    "tradeoff": {"tradeoff", "trade-off", "instead", "compared", "constraint", "rather"},
    "repair": {"debug", "fixed", "failed", "bug", "error"},
}
_PROBLEM_SCORES = {0: 10.0, 1: 45.0, 2: 70.0, 3: 90.0, 4: 100.0}
_SYSTEM = (
    "You copy short evidence quotes from the candidate's own words. "
    "Return only a JSON object. Do not use markdown."
)


class ScoreError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class SpeechTurn:
    speaker: str
    text: str


@dataclass(frozen=True)
class ChecklistTopic:
    query_id: str
    question: str
    dimension: str


@dataclass(frozen=True)
class DimensionDraft:
    key: str
    label: str
    score: float
    evidence: str
    note: str


@dataclass(frozen=True)
class PerformanceDraft:
    """Interview-only score. Suitability and the CV aggregate do not read this draft."""

    overall_score: float
    summary: str
    dimensions: list[DimensionDraft]
    llm_tier: str
    fallback_used: bool


def conductor_label(value: str) -> str:
    if value == "agent":
        return "Agent"
    return "Recruiter"


def score_interview(
    turns: list[SpeechTurn],
    checklist: list[ChecklistTopic],
    quotes: dict[str, str] | None = None,
    *,
    llm_tier: str = "none",
    fallback_used: bool = False,
) -> PerformanceDraft:
    """Assign six interview dimensions. A quote counts only when the candidate said it."""
    speech = _candidate_text(turns)
    proposed = quotes or {}
    raw = [
        _technical(speech, checklist),
        _communication(turns),
        _relevance(turns),
        _problem_solving(speech),
        _experience(speech),
        _alignment(speech, checklist),
    ]
    dimensions: list[DimensionDraft] = []
    for (key, label), (score, evidence, note) in zip(DIMENSIONS, raw, strict=True):
        kept = evidence
        if speech and proposed.get(key, "").strip():
            ok, snippet = anchored_quote(proposed[key], speech)
            if ok and snippet and len(_tokens(snippet)) >= 6:
                kept = snippet
        dimensions.append(DimensionDraft(key=key, label=label, score=score, evidence=kept, note=note))
    overall = round(sum(item.score for item in dimensions) / len(dimensions), 1)
    return PerformanceDraft(
        overall_score=overall,
        summary=f"Interview performance is {overall:.1f} out of 100. This score uses only the interview.",
        dimensions=dimensions,
        llm_tier=llm_tier,
        fallback_used=fallback_used,
    )


async def draft_interview_score(
    llm: FallbackLLMManager,
    turns: list[SpeechTurn],
    checklist: list[ChecklistTopic],
) -> PerformanceDraft:
    speech = _candidate_text(turns)
    if not speech:
        return score_interview(turns, checklist)
    try:
        response = await llm.complete(_quote_prompt(speech, checklist), system=_SYSTEM)
    except LLMFallbackExhaustedError:
        return score_interview(turns, checklist, fallback_used=True)
    try:
        payload = parse_json_object(response.content)
    except JobGraphError:
        payload = {}
    return score_interview(
        turns,
        checklist,
        quotes=_quotes(payload),
        llm_tier=response.tier.value,
        fallback_used=response.fallback_used,
    )


async def read_interview_score(db: AsyncSession, candidate_id: uuid.UUID) -> InterviewScoreRead:
    interview = await _ended_interview(db, candidate_id)
    stored = await _load(db, interview.id)
    if stored is None:
        raise ScoreError("INTERVIEW_SCORE_NOT_FOUND", "The interview has not been scored yet.", 404)
    return _to_read(candidate_id, stored)


async def build_interview_score(
    db: AsyncSession,
    llm: FallbackLLMManager,
    candidate_id: uuid.UUID,
) -> InterviewScoreRead:
    interview = await _ended_interview(db, candidate_id)
    stored = await _load(db, interview.id)
    if stored is not None:
        return _to_read(candidate_id, stored)
    segments = await _segments(db, interview.id)
    await store_interview_score(db, llm, interview, segments)
    await db.commit()
    saved = await _load(db, interview.id)
    if saved is None:
        raise ScoreError("INTERVIEW_SCORE_EMPTY", "The interview score could not be saved.", 409)
    return _to_read(candidate_id, saved)


async def store_interview_score(
    db: AsyncSession,
    llm: FallbackLLMManager,
    interview: InterviewSession,
    segments: list[TranscriptSegment],
) -> None:
    existing = await db.scalar(select(InterviewPerformance.id).where(InterviewPerformance.session_id == interview.id))
    if existing is not None:
        return
    checklist = await _checklist(db, interview.job_version_id)
    turns = [SpeechTurn(segment.speaker, segment.text) for segment in segments if segment.text.strip()]
    draft = await draft_interview_score(llm, turns, checklist)
    performance = InterviewPerformance(
        id=uuid.uuid4(),
        session_id=interview.id,
        overall_score=draft.overall_score,
        summary=draft.summary,
        llm_tier=draft.llm_tier,
        fallback_used=draft.fallback_used,
        created_at=datetime.now(UTC),
    )
    db.add(performance)
    await db.flush()
    for sequence, item in enumerate(draft.dimensions, start=1):
        db.add(
            InterviewPerformanceDimension(
                id=uuid.uuid4(),
                performance_id=performance.id,
                dimension_key=item.key,
                label=item.label,
                score=item.score,
                evidence=item.evidence,
                note=item.note,
                sequence=sequence,
            )
        )


async def read_candidate_analysis(db: AsyncSession, candidate_id: uuid.UUID) -> InterviewAnalysis:
    if await db.get(Candidate, candidate_id) is None:
        raise ScoreError("CANDIDATE_NOT_FOUND", "Candidate not found.", 404)
    interview = await db.scalar(select(InterviewSession).where(InterviewSession.candidate_id == candidate_id))
    if interview is None:
        raise ScoreError("ANALYSIS_NOT_FOUND", "This candidate has no interview analysis yet.", 404)
    analysis = await db.scalar(
        select(InterviewAnalysis)
        .where(InterviewAnalysis.session_id == interview.id)
        .options(selectinload(InterviewAnalysis.pairs))
    )
    if analysis is None:
        raise analysis_absence(interview.processing_status or "")
    return analysis


def analysis_absence(processing_status: str) -> ScoreError:
    """The analysis row is missing. Say whether the write failed, is still running, or never started."""
    if processing_status == "failed":
        return ScoreError(
            "ANALYSIS_FAILED",
            "The question and answer analysis did not finish. Run it again.",
            409,
        )
    if processing_status == "pending":
        return ScoreError(
            "ANALYSIS_PENDING",
            "The question and answer analysis is still being written.",
            404,
        )
    return ScoreError("ANALYSIS_NOT_FOUND", "The question and answer analysis is not ready.", 404)


async def list_interview_history(db: AsyncSession) -> list[InterviewHistoryRead]:
    from app.services.interview_practice import is_practice_job

    rows = list(
        (
            await db.scalars(
                select(InterviewSession)
                .options(
                    selectinload(InterviewSession.candidate)
                    .selectinload(Candidate.version)
                    .selectinload(JobVersion.job),
                    selectinload(InterviewSession.performance),
                )
                .order_by(nulls_last(desc(InterviewSession.ended_at)), desc(InterviewSession.created_at))
            )
        ).all()
    )
    history: list[InterviewHistoryRead] = []
    for row in rows:
        candidate = row.candidate
        if candidate is None or candidate.version is None or candidate.version.job is None:
            continue
        if is_practice_job(candidate.version.job.mail_subject):
            continue
        score = row.performance.overall_score if row.performance is not None else None
        history.append(
            InterviewHistoryRead(
                session_id=row.id,
                candidate_id=candidate.id,
                full_name=candidate.full_name.strip() or "Unnamed",
                job_title=candidate.version.job.title,
                conductor=conductor_label(row.conductor or ""),
                status=row.status,
                ended_at=row.ended_at,
                interview_score=score,
            )
        )
    return history


def _technical(speech: str, checklist: list[ChecklistTopic]) -> tuple[float, str, str]:
    if not speech:
        return 0.0, "", "No candidate speech was captured."
    items = [item for item in checklist if item.dimension == "technical"]
    if items:
        covered = [item for item in items if _covered(item.question, speech)]
        wanted: set[str] = set()
        for item in covered or items:
            wanted.update(_content(item.question))
        return (
            _points(100 * len(covered) / len(items)),
            _best_sentence(speech, wanted),
            f"The answers cover {len(covered)} of {len(items)} technical requirements.",
        )
    quote = _sentence_with(speech, _MECHANISM)
    if quote:
        return 70.0, quote, "The role has no technical checklist item. The answer describes a method."
    return (
        20.0,
        _fallback_quote(speech),
        "The role has no technical checklist item, and the answer does not describe a method.",
    )


def _communication(turns: list[SpeechTurn]) -> tuple[float, str, str]:
    answers = [turn.text.strip() for turn in turns if turn.speaker == "candidate" and turn.text.strip()]
    if not answers:
        return 0.0, "", "No candidate speech was captured."
    clear = [text for text in answers if 8 <= len(_tokens(text)) <= 90]
    quote = max(clear or answers, key=lambda text: len(_tokens(text)))
    return (
        _points(100 * len(clear) / len(answers)),
        quote,
        f"{len(clear)} of {len(answers)} {'answer is' if len(answers) == 1 else 'answers are'} long enough to follow.",
    )


def _relevance(turns: list[SpeechTurn]) -> tuple[float, str, str]:
    speech = _candidate_text(turns)
    if not speech:
        return 0.0, "", "No candidate speech was captured."
    scored: list[tuple[float, str, str]] = []
    for question, answer in _pairs(turns):
        words = set(_content(question))
        if not question or not words or not answer:
            continue
        overlap = len(words & set(_content(answer))) / len(words)
        scored.append((overlap, answer, question))
    if not scored:
        return 25.0, _fallback_quote(speech), "The candidate spoke without a question to answer."
    best = max(scored, key=lambda item: item[0])
    wanted = set(_content(best[2])) or set(_content(best[1]))
    mean = sum(item[0] for item in scored) / len(scored)
    return (
        _points(mean * 100),
        _best_sentence(best[1], wanted),
        f"Answers overlap the questions on {len(scored)} exchanges.",
    )


def _problem_solving(speech: str) -> tuple[float, str, str]:
    if not speech:
        return 0.0, "", "No candidate speech was captured."
    found = _problem_categories(speech)
    quote = _sentence_with(speech, set().union(*_PROBLEM.values())) or _fallback_quote(speech)
    return (
        _PROBLEM_SCORES[min(len(found), 4)],
        quote,
        f"The answers show {len(found)} of 4 problem-solving signals.",
    )


def _experience(speech: str) -> tuple[float, str, str]:
    if not speech:
        return 0.0, "", "No candidate speech was captured."
    specific = [sentence for sentence in _sentences(speech) if _specific(sentence)]
    if not specific:
        return 15.0, _fallback_quote(speech), "The answers do not give a specific example."
    quote = max(specific, key=lambda sentence: len(_tokens(sentence)))
    return (
        _points(min(100.0, 35.0 * len(specific))),
        quote,
        f"The answers include {len(specific)} specific {'example' if len(specific) == 1 else 'examples'}.",
    )


def _alignment(speech: str, checklist: list[ChecklistTopic]) -> tuple[float, str, str]:
    if not speech:
        return 0.0, "", "No candidate speech was captured."
    if not checklist:
        return 25.0, _fallback_quote(speech), "This role has no checklist to compare with the interview."
    covered = [item for item in checklist if _covered(item.question, speech)]
    wanted: set[str] = set()
    for item in covered or checklist:
        wanted.update(_content(item.question))
    return (
        _points(100 * len(covered) / len(checklist)),
        _best_sentence(speech, wanted),
        f"The answers cover {len(covered)} of {len(checklist)} checklist requirements.",
    )


def _covered(question: str, speech: str) -> bool:
    words = set(_content(question))
    if not words:
        return False
    need = 1 if len(words) == 1 else 2
    return len(words & set(_content(speech))) >= need


def _problem_categories(speech: str) -> set[str]:
    tokens = set(_tokens(speech))
    return {name for name, words in _PROBLEM.items() if tokens & words}


def _specific(sentence: str) -> bool:
    if len(_tokens(sentence)) < 8:
        return False
    return _DIGIT.search(sentence) is not None or _EXAMPLE.search(sentence) is not None


def _pairs(turns: list[SpeechTurn]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    question: str | None = None
    answer: list[str] = []

    def flush() -> None:
        nonlocal question, answer
        if question is None and not answer:
            return
        pairs.append((question or "", " ".join(answer).strip()))
        question = None
        answer = []

    for turn in turns:
        text = turn.text.strip()
        if not text:
            continue
        if turn.speaker == "recruiter":
            if question is not None or answer:
                flush()
            question = text
            continue
        if turn.speaker == "candidate":
            answer.append(text)
    flush()
    return pairs


def _candidate_text(turns: list[SpeechTurn]) -> str:
    return " ".join(turn.text.strip() for turn in turns if turn.speaker == "candidate" and turn.text.strip()).strip()


def _tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN.finditer(text)]


def _content(text: str) -> list[str]:
    return [token for token in _tokens(text) if len(token) >= 4 and token not in _STOP]


def _sentences(text: str) -> list[str]:
    return [" ".join(match.group(0).split()) for match in _SENTENCE.finditer(text) if match.group(0).strip()]


def _best_sentence(speech: str, wanted: set[str]) -> str:
    if wanted:
        chosen = _sentence_with(speech, wanted)
        if chosen:
            return chosen
    return _fallback_quote(speech)


def _sentence_with(speech: str, wanted: set[str]) -> str:
    hits = [sentence for sentence in _sentences(speech) if set(_tokens(sentence)) & wanted]
    if not hits:
        return ""
    return max(hits, key=lambda sentence: (len(set(_tokens(sentence)) & wanted), len(_tokens(sentence))))


def _fallback_quote(speech: str) -> str:
    sentences = _sentences(speech)
    if not sentences:
        return speech.strip()
    return max(sentences, key=lambda sentence: len(_tokens(sentence)))


def _points(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _quote_prompt(speech: str, checklist: list[ChecklistTopic]) -> str:
    lines = [f"- {key}: {label}" for key, label in DIMENSIONS]
    topics = [f"- {item.dimension}: {item.question}" for item in checklist]
    return (
        "Copy one short evidence quote from the candidate speech for each dimension. "
        "Leave the quote empty when the speech does not support that dimension. "
        "Do not score the candidate and do not mention the CV.\n"
        'Return JSON {"evidence":[{"key":"technical_competency","quote":""}]}\n'
        "Dimensions:\n"
        + "\n".join(lines)
        + "\nChecklist:\n"
        + ("\n".join(topics) if topics else "none")
        + "\nCandidate speech:\n"
        + speech[:12000]
    )


def _quotes(payload: dict[str, object]) -> dict[str, str]:
    raw = payload.get("evidence")
    if not isinstance(raw, list):
        return {}
    allowed = {key for key, _label in DIMENSIONS}
    found: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        if key in allowed:
            found[key] = str(item.get("quote") or "")
    return found


async def _ended_interview(db: AsyncSession, candidate_id: uuid.UUID) -> InterviewSession:
    if await db.get(Candidate, candidate_id) is None:
        raise ScoreError("CANDIDATE_NOT_FOUND", "Candidate not found.", 404)
    interview = await db.scalar(select(InterviewSession).where(InterviewSession.candidate_id == candidate_id))
    if interview is None or interview.status != "ended":
        raise ScoreError("INTERVIEW_NOT_ENDED", "Interview scoring runs after the interview ends.", 409)
    return interview


async def _checklist(db: AsyncSession, version_id: uuid.UUID) -> list[ChecklistTopic]:
    rows = list((await db.scalars(select(JobChecklistQuery).where(JobChecklistQuery.version_id == version_id))).all())
    rows.sort(key=lambda query: int(query.query_id[1:]) if query.query_id[1:].isdigit() else 0)
    return [ChecklistTopic(query.query_id, query.question, query.dimension) for query in rows]


async def _segments(db: AsyncSession, session_id: uuid.UUID) -> list[TranscriptSegment]:
    result = await db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.start_time, TranscriptSegment.created_at)
    )
    return list(result.all())


async def _load(db: AsyncSession, session_id: uuid.UUID) -> InterviewPerformance | None:
    return await db.scalar(
        select(InterviewPerformance)
        .where(InterviewPerformance.session_id == session_id)
        .options(selectinload(InterviewPerformance.dimensions))
    )


def _to_read(candidate_id: uuid.UUID, performance: InterviewPerformance) -> InterviewScoreRead:
    ordered = sorted(performance.dimensions, key=lambda item: item.sequence)
    return InterviewScoreRead(
        candidate_id=candidate_id,
        overall_score=performance.overall_score,
        summary=performance.summary,
        llm_tier=performance.llm_tier,
        fallback_used=performance.fallback_used,
        dimensions=[
            PerformanceDimensionRead(
                key=item.dimension_key,
                label=item.label,
                score=item.score,
                evidence=item.evidence,
                note=item.note,
            )
            for item in ordered
        ],
    )
