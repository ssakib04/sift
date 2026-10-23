import uuid
from datetime import UTC, datetime

from jinja2 import Environment, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.llm_fallback import FallbackLLMManager, LLMFallbackExhaustedError
from app.graphs.master_assessment_graph import (
    AssessmentGraphError,
    CV_WEIGHT,
    INTERVIEW_WEIGHT,
    MCQ_WEIGHT,
    build_master_assessment_graph,
    suitability_label,
)
from app.models.candidate import (
    AssessmentComponentScore,
    AssessmentStrength,
    AssessmentWeakness,
    Candidate,
    ConsolidatedAssessment,
    EvidenceLink,
    InterviewAnalysis,
    InterviewSession,
    McqAttempt,
    ScoreSnapshot,
)
from app.models.job import JobVersion
from app.schemas.assessment import (
    AssessmentRead,
    ComparisonRowRead,
    ComponentScoresRead,
    JobComparisonRead,
    TraceLinkRead,
)
from app.services.screening import list_candidate_groups

COMPONENT_ORDER = (
    "cv_screening",
    "mcq_quiz",
    "interview_qa",
    "technical_dimension",
    "experience_dimension",
    "qualification_dimension",
)
_CITED = {"cv", "transcript"}

_REPORT = Environment(autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True).from_string(
    """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ report.full_name }} evaluation</title>
  <style>
    body { font-family: Georgia, serif; color: #1c1412; max-width: 800px; margin: 2rem auto; line-height: 1.45; }
    h1, h2 { font-weight: 600; }
    table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
    th, td { border-bottom: 1px solid #ddd; text-align: left; padding: 0.4rem 0.3rem; vertical-align: top; }
    .muted { color: #5c534e; }
  </style>
</head>
<body>
  <p class="muted">Sift candidate evaluation</p>
  <h1>{{ report.full_name }}</h1>
  <p>{{ report.job_title }}</p>
  <p><strong>{{ report.suitability_label }}</strong>
    {% if report.overall_score is not none %} · {{ "%.1f"|format(report.overall_score) }}{% endif %}
  </p>
  <p class="muted">Weights locked at CV {{ "%.0f"|format(report.cv_weight * 100) }}%,
    MCQ {{ "%.0f"|format(report.mcq_weight * 100) }}%,
    interview Q&amp;A {{ "%.0f"|format(report.interview_weight * 100) }}%.
    Generated {{ generated }}.</p>
  <h2>Component scores</h2>
  <table>
    <thead><tr><th>Component</th><th>Score</th></tr></thead>
    <tbody>
      {% for label, value in components %}
      <tr><td>{{ label }}</td><td>{{ value }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
  <h2>Narrative</h2>
  <p>{{ report.narrative }}</p>
  <h2>Strengths</h2>
  {% if report.strengths %}<ul>{% for item in report.strengths %}<li>{{ item }}</li>{% endfor %}</ul>
  {% else %}<p class="muted">None recorded.</p>{% endif %}
  <h2>Weaknesses</h2>
  {% if report.weaknesses %}<ul>{% for item in report.weaknesses %}<li>{{ item }}</li>{% endfor %}</ul>
  {% else %}<p class="muted">None recorded.</p>{% endif %}
  <h2>Evidence gaps</h2>
  {% if report.evidence_gaps %}<ul>{% for item in report.evidence_gaps %}<li>{{ item }}</li>{% endfor %}</ul>
  {% else %}<p class="muted">None recorded.</p>{% endif %}
  <h2>Traceability</h2>
  <table>
    <thead><tr><th>Claim</th><th>Source</th><th>Reference</th><th>Evidence</th></tr></thead>
    <tbody>
      {% for link in report.traceability %}
      <tr>
        <td>{{ link.claim }}</td>
        <td>{{ link.source_type }}</td>
        <td>{{ link.source_reference }}</td>
        <td>{{ link.evidence }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
"""
)


class AssessmentError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def inputs_from_candidate(candidate: Candidate) -> dict[str, object]:
    """Load the three stored inputs. An unsubmitted quiz contributes no score."""
    questions = {query.query_id: query.question for query in candidate.version.queries} if candidate.version is not None else {}
    analysis = candidate.interview_session.analysis if candidate.interview_session is not None else None
    return {
        "candidate_id": str(candidate.id),
        "cv_screening": _cv_input(candidate.snapshot, questions),
        "mcq_score": _mcq_input(candidate.quiz_attempt),
        "qa_analysis": _qa_input(analysis),
        "tier_notes": [],
        "fallback_flags": [],
    }


def key_gap_text(gaps: list[str], weaknesses: list[str], *, assessed: bool) -> str:
    if not assessed:
        return "Not assessed"
    if gaps:
        return gaps[0]
    if weaknesses:
        return weaknesses[0]
    return "None"


def render_assessment_report(report: AssessmentRead) -> str:
    scores = report.component_scores
    components = [
        ("CV screening", _cell(scores.cv_screening)),
        ("MCQ quiz", _cell(scores.mcq_quiz)),
        ("Interview Q&A", _cell(scores.interview_qa)),
        ("Technical", _cell(scores.technical_dimension)),
        ("Experience", _cell(scores.experience_dimension)),
        ("Qualification", _cell(scores.qualification_dimension)),
    ]
    generated = report.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return _REPORT.render(report=report, components=components, generated=generated)


async def build_consolidated_assessment(
    session: AsyncSession,
    llm: FallbackLLMManager,
    candidate_id: uuid.UUID,
) -> AssessmentRead:
    candidate = await _load_candidate(session, candidate_id)
    if candidate is None:
        raise AssessmentError("CANDIDATE_NOT_FOUND", "Candidate not found.", 404)
    try:
        result = await build_master_assessment_graph(llm)(inputs_from_candidate(candidate))
    except AssessmentGraphError as exc:
        raise AssessmentError("ASSESSMENT_INPUT_INVALID", str(exc), 400) from exc
    except LLMFallbackExhaustedError as exc:
        raise AssessmentError("LLM_UNAVAILABLE", "The assessment model is unavailable.", 503) from exc
    await _save(session, candidate, result)
    await session.commit()
    session.expire(candidate, ["consolidated_assessment"])
    fresh = await session.scalar(
        select(Candidate)
        .where(Candidate.id == candidate.id)
        .options(*_candidate_loader())
        .execution_options(populate_existing=True)
    )
    if fresh is None or fresh.consolidated_assessment is None:
        raise AssessmentError("ASSESSMENT_NOT_FOUND", "The master assessment could not be saved.", 500)
    return assessment_read(fresh, fresh.consolidated_assessment)


async def get_assessment(session: AsyncSession, candidate_id: uuid.UUID) -> AssessmentRead:
    candidate = await _load_candidate(session, candidate_id)
    if candidate is None:
        raise AssessmentError("CANDIDATE_NOT_FOUND", "Candidate not found.", 404)
    row = candidate.consolidated_assessment
    if row is None:
        raise AssessmentError("ASSESSMENT_NOT_FOUND", "This candidate has no master assessment yet.", 404)
    return assessment_read(candidate, row)


async def list_comparisons(session: AsyncSession) -> list[JobComparisonRead]:
    groups = await list_candidate_groups(session)
    ids = [candidate.id for group in groups for candidate in group.candidates]
    stored = await _assessments_by_candidate(session, ids)
    comparisons: list[JobComparisonRead] = []
    for group in groups:
        rows: list[ComparisonRowRead] = []
        for candidate in group.candidates:
            assessment = stored.get(candidate.id)
            rows.append(_comparison_row(candidate.id, candidate.full_name, assessment))
        rows.sort(key=lambda row: (row.overall_score is None, -(row.overall_score or 0), row.full_name.casefold()))
        comparisons.append(
            JobComparisonRead(
                job_id=group.job_id,
                job_title=group.job_title,
                cv_weight=float(CV_WEIGHT),
                mcq_weight=float(MCQ_WEIGHT),
                interview_weight=float(INTERVIEW_WEIGHT),
                rows=rows,
            )
        )
    return comparisons


def assessment_read(candidate: Candidate, row: ConsolidatedAssessment) -> AssessmentRead:
    job_title = ""
    if candidate.version is not None and candidate.version.job is not None:
        job_title = candidate.version.job.title
    scores = {item.component: item.score for item in row.component_scores}
    links = sorted(row.evidence_links, key=lambda item: item.sequence)
    suitability = row.overall_suitability
    return AssessmentRead(
        candidate_id=candidate.id,
        full_name=candidate.full_name,
        job_title=job_title,
        overall_suitability=suitability,  # type: ignore[arg-type]
        suitability_label=suitability_label(suitability),
        overall_score=row.overall_score,
        component_scores=ComponentScoresRead(
            cv_screening=scores.get("cv_screening"),
            mcq_quiz=scores.get("mcq_quiz"),
            interview_qa=scores.get("interview_qa"),
            technical_dimension=scores.get("technical_dimension"),
            experience_dimension=scores.get("experience_dimension"),
            qualification_dimension=scores.get("qualification_dimension"),
        ),
        strengths=[item.text for item in sorted(row.strengths, key=lambda item: item.sequence)],
        weaknesses=[item.text for item in sorted(row.weaknesses, key=lambda item: item.sequence)],
        evidence_gaps=[item.claim for item in links if item.source_type == "gap"],
        traceability=[
            TraceLinkRead(
                claim=item.claim,
                source_type=item.source_type,
                source_reference=item.source_reference,
                evidence=item.evidence,
            )
            for item in links
            if item.source_type in _CITED
        ],
        narrative=row.narrative,
        cv_weight=row.cv_weight,
        mcq_weight=row.mcq_weight,
        interview_weight=row.interview_weight,
        llm_tier=row.llm_tier,
        fallback_used=row.fallback_used,
        created_at=row.created_at,
    )


async def _save(session: AsyncSession, candidate: Candidate, result: dict[str, object]) -> ConsolidatedAssessment:
    existing = candidate.consolidated_assessment
    if existing is not None:
        await session.delete(existing)
        await session.flush()
    scores = result.get("component_scores") if isinstance(result.get("component_scores"), dict) else {}
    suitability = str(result.get("overall_suitability") or "insufficient_evidence")
    overall = result.get("overall_score")
    row = ConsolidatedAssessment(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        job_version_id=candidate.job_version_id,
        overall_suitability=suitability,
        overall_score=float(overall) if isinstance(overall, int | float) else None,
        narrative=str(result.get("narrative") or ""),
        cv_weight=float(CV_WEIGHT),
        mcq_weight=float(MCQ_WEIGHT),
        interview_weight=float(INTERVIEW_WEIGHT),
        llm_tier=str(result.get("llm_tier") or "none"),
        fallback_used=bool(result.get("fallback_used")),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    for name in COMPONENT_ORDER:
        value = scores.get(name) if isinstance(scores, dict) else None
        session.add(
            AssessmentComponentScore(
                id=uuid.uuid4(),
                assessment_id=row.id,
                component=name,
                score=float(value) if isinstance(value, int | float) else None,
            )
        )
    for sequence, text in enumerate(_strings(result.get("strengths"))):
        session.add(AssessmentStrength(id=uuid.uuid4(), assessment_id=row.id, sequence=sequence, text=text))
    for sequence, text in enumerate(_strings(result.get("weaknesses"))):
        session.add(AssessmentWeakness(id=uuid.uuid4(), assessment_id=row.id, sequence=sequence, text=text))
    sequence = 0
    for item in _trace_items(result.get("traceability")):
        session.add(
            EvidenceLink(
                id=uuid.uuid4(),
                assessment_id=row.id,
                sequence=sequence,
                claim=item["claim"],
                source_type=item["source_type"],
                source_reference=item["source_reference"],
                evidence=item["evidence"],
            )
        )
        sequence += 1
    for gap in _strings(result.get("evidence_gaps")):
        session.add(
            EvidenceLink(
                id=uuid.uuid4(),
                assessment_id=row.id,
                sequence=sequence,
                claim=gap,
                source_type="gap",
                source_reference="",
                evidence=gap,
            )
        )
        sequence += 1
    await session.flush()
    return row


def _candidate_loader():
    assessment = selectinload(Candidate.consolidated_assessment)
    return (
        selectinload(Candidate.snapshot).selectinload(ScoreSnapshot.evaluations),
        selectinload(Candidate.quiz_attempt),
        selectinload(Candidate.interview_session).selectinload(InterviewSession.analysis).selectinload(InterviewAnalysis.pairs),
        selectinload(Candidate.version).selectinload(JobVersion.job),
        selectinload(Candidate.version).selectinload(JobVersion.queries),
        assessment.selectinload(ConsolidatedAssessment.component_scores),
        assessment.selectinload(ConsolidatedAssessment.strengths),
        assessment.selectinload(ConsolidatedAssessment.weaknesses),
        assessment.selectinload(ConsolidatedAssessment.evidence_links),
    )


async def _load_candidate(session: AsyncSession, candidate_id: uuid.UUID) -> Candidate | None:
    statement = select(Candidate).where(Candidate.id == candidate_id).options(*_candidate_loader())
    return await session.scalar(statement)


async def _assessments_by_candidate(
    session: AsyncSession,
    candidate_ids: list[uuid.UUID],
) -> dict[uuid.UUID, ConsolidatedAssessment]:
    if not candidate_ids:
        return {}
    statement = (
        select(ConsolidatedAssessment)
        .where(ConsolidatedAssessment.candidate_id.in_(candidate_ids))
        .options(
            selectinload(ConsolidatedAssessment.component_scores),
            selectinload(ConsolidatedAssessment.strengths),
            selectinload(ConsolidatedAssessment.weaknesses),
            selectinload(ConsolidatedAssessment.evidence_links),
        )
    )
    rows = list((await session.scalars(statement)).unique().all())
    return {row.candidate_id: row for row in rows}


def _comparison_row(candidate_id: uuid.UUID, full_name: str, row: ConsolidatedAssessment | None) -> ComparisonRowRead:
    if row is None:
        return ComparisonRowRead(
            candidate_id=candidate_id,
            full_name=full_name,
            overall_score=None,
            overall_suitability=None,
            suitability_label="",
            technical_dimension=None,
            experience_dimension=None,
            qualification_dimension=None,
            mcq_score=None,
            interview_qa=None,
            key_gap=key_gap_text([], [], assessed=False),
        )
    scores = {item.component: item.score for item in row.component_scores}
    links = sorted(row.evidence_links, key=lambda item: item.sequence)
    gaps = [item.claim for item in links if item.source_type == "gap"]
    weaknesses = [item.text for item in sorted(row.weaknesses, key=lambda item: item.sequence)]
    return ComparisonRowRead(
        candidate_id=candidate_id,
        full_name=full_name,
        overall_score=row.overall_score,
        overall_suitability=row.overall_suitability,  # type: ignore[arg-type]
        suitability_label=suitability_label(row.overall_suitability),
        technical_dimension=scores.get("technical_dimension"),
        experience_dimension=scores.get("experience_dimension"),
        qualification_dimension=scores.get("qualification_dimension"),
        mcq_score=scores.get("mcq_quiz"),
        interview_qa=scores.get("interview_qa"),
        key_gap=key_gap_text(gaps, weaknesses, assessed=True),
    )


def _cv_input(snapshot: ScoreSnapshot | None, questions: dict[str, str]) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "aggregate_score": snapshot.aggregate_score,
        "technical_score": snapshot.technical_score,
        "experience_score": snapshot.experience_score,
        "qualification_score": snapshot.qualification_score,
        "evaluations": [
            {
                "query_id": item.query_id,
                "question": questions.get(item.query_id, ""),
                "status": item.status,
                "evidence": item.evidence,
            }
            for item in snapshot.evaluations
        ],
    }


def _mcq_input(attempt: McqAttempt | None) -> int | None:
    if attempt is None or attempt.submitted_at is None or attempt.score is None:
        return None
    return attempt.score


def _qa_input(analysis: InterviewAnalysis | None) -> dict[str, object] | None:
    if analysis is None:
        return None
    pairs = sorted(analysis.pairs, key=lambda item: item.sequence)
    return {
        "relevance": analysis.relevance,
        "technical_accuracy": analysis.technical_accuracy,
        "completeness": analysis.completeness,
        "articulation": analysis.articulation,
        "gaps": list(analysis.gaps),
        "pairs": [
            {
                "pair_id": pair.pair_id,
                "citation": pair.citation,
                "answer": pair.answer,
                "relevance": pair.relevance,
                "technical_accuracy": pair.technical_accuracy,
                "completeness": pair.completeness,
                "articulation": pair.articulation,
            }
            for pair in pairs
        ],
    }


def _strings(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _trace_items(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        source_type = str(item.get("source_type") or "").strip()
        reference = str(item.get("source_reference") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        if claim and source_type in _CITED and reference and evidence:
            items.append(
                {
                    "claim": claim,
                    "source_type": source_type,
                    "source_reference": reference[:80],
                    "evidence": evidence,
                }
            )
    return items


def _cell(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}"


_assessment_running: set[uuid.UUID] = set()
_assessment_failed: dict[uuid.UUID, str] = {}


def claim_assessment_run(candidate_id: uuid.UUID) -> bool:
    """One build per candidate. A second click waits on the build already running."""
    if candidate_id in _assessment_running:
        return False
    _assessment_failed.pop(candidate_id, None)
    _assessment_running.add(candidate_id)
    return True


def finish_assessment_run(candidate_id: uuid.UUID, message: str | None) -> None:
    if message:
        _assessment_failed[candidate_id] = message
    else:
        _assessment_failed.pop(candidate_id, None)
    _assessment_running.discard(candidate_id)


def assessment_wait_error(candidate_id: uuid.UUID) -> AssessmentError | None:
    if candidate_id in _assessment_running:
        return AssessmentError("ASSESSMENT_PENDING", "The master assessment is still being written.", 404)
    message = _assessment_failed.get(candidate_id)
    if message:
        return AssessmentError("ASSESSMENT_FAILED", message, 409)
    return None


def apply_assessment_run(candidate_id: uuid.UUID, report: AssessmentRead) -> AssessmentRead:
    if candidate_id in _assessment_running:
        return report.model_copy(update={"run_state": "running", "run_message": ""})
    message = _assessment_failed.get(candidate_id)
    if message:
        return report.model_copy(update={"run_state": "failed", "run_message": message})
    return report.model_copy(update={"run_state": "idle", "run_message": ""})


async def run_assessment_job(llm: FallbackLLMManager, candidate_id: uuid.UUID) -> None:
    """Build the report after the HTTP response has already returned."""
    from app.core.database import SessionFactory

    message: str | None = None
    try:
        async with SessionFactory() as session:
            await build_consolidated_assessment(session, llm, candidate_id)
    except AssessmentError as exc:
        message = exc.message
    except Exception:
        message = "The master assessment could not be built."
    finally:
        finish_assessment_run(candidate_id, message)
