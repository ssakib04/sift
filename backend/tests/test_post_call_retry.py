import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.assessment import AssessmentRead, ComponentScoresRead
from app.services.assessment import (
    apply_assessment_run,
    assessment_wait_error,
    claim_assessment_run,
    finish_assessment_run,
)
from app.services.interview_score import analysis_absence


def test_a_missing_analysis_says_whether_it_failed() -> None:
    failed = analysis_absence("failed")
    pending = analysis_absence("pending")
    missing = analysis_absence("")
    assert failed.code == "ANALYSIS_FAILED"
    assert failed.status_code == 409
    assert pending.code == "ANALYSIS_PENDING"
    assert missing.code == "ANALYSIS_NOT_FOUND"


def test_one_assessment_build_runs_at_a_time() -> None:
    candidate_id = uuid.uuid4()
    assert claim_assessment_run(candidate_id) is True
    assert claim_assessment_run(candidate_id) is False
    waiting = assessment_wait_error(candidate_id)
    assert waiting is not None
    assert waiting.code == "ASSESSMENT_PENDING"
    finish_assessment_run(candidate_id, "The assessment model is unavailable.")
    failed = assessment_wait_error(candidate_id)
    assert failed is not None
    assert failed.code == "ASSESSMENT_FAILED"
    assert failed.message == "The assessment model is unavailable."
    marked = apply_assessment_run(candidate_id, _report())
    assert marked.run_state == "failed"
    assert marked.run_message == "The assessment model is unavailable."
    assert claim_assessment_run(candidate_id) is True
    assert apply_assessment_run(candidate_id, _report()).run_state == "running"
    finish_assessment_run(candidate_id, None)
    assert assessment_wait_error(candidate_id) is None
    assert apply_assessment_run(candidate_id, _report()).run_state == "idle"


def test_claim_check_replaces_an_earlier_result() -> None:
    source = (Path(__file__).resolve().parents[1] / "app/services/cv_claims.py").read_text(encoding="utf-8")
    start = source.index("async def build_claim_verification")
    body = source[start : source.index("\nasync def ", start + 1)]
    assert "await db.delete(existing)" in body
    assert "return _to_read(candidate_id, existing)" not in body


def test_retry_routes_return_before_the_model_finishes() -> None:
    root = Path(__file__).resolve().parents[1]
    analysis = (root / "app/api/v1/interview_reports.py").read_text(encoding="utf-8")
    assessment = (root / "app/api/v1/assessments.py").read_text(encoding="utf-8")
    assert '@router.post("/candidates/{candidate_id}/interview-analysis"' in analysis
    assert "request_interview_analysis" in analysis
    assert "AssessmentRunRead" in assessment
    assert "background.add_task(run_assessment_job, llm, candidate_id)" in assessment


def _report() -> AssessmentRead:
    return AssessmentRead(
        candidate_id=uuid.uuid4(),
        full_name="Kaji Sadman Sakib",
        job_title="Backend Engineer",
        overall_suitability="insufficient_evidence",
        suitability_label="Insufficient evidence",
        overall_score=None,
        component_scores=ComponentScoresRead(),
        strengths=[],
        weaknesses=[],
        evidence_gaps=[],
        traceability=[],
        narrative="",
        cv_weight=0.3,
        mcq_weight=0.2,
        interview_weight=0.5,
        llm_tier="none",
        fallback_used=False,
        created_at=datetime.now(UTC),
    )
