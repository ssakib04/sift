from datetime import UTC, datetime
from uuid import uuid4

from app.api.v1.assessments import router as assessment_router
from app.api.v1.auth import require_recruiter
from app.models.candidate import InterviewAnalysis, McqAttempt, QAPair, QueryEvaluation, ScoreSnapshot
from app.schemas.assessment import AssessmentRead, ComponentScoresRead
from app.schemas.quiz import CandidateQuizRead
from app.services.assessment import _cv_input, _mcq_input, _qa_input, key_gap_text, render_assessment_report


def test_candidate_quiz_payload_has_no_master_score() -> None:
    assert "score" not in CandidateQuizRead.model_fields
    assert "mcq_score" not in CandidateQuizRead.model_fields
    assert "overall_score" not in CandidateQuizRead.model_fields


def test_assessment_routes_require_a_recruiter() -> None:
    found = {
        (route.path, method)
        for route in assessment_router.routes
        for method in route.methods
        if method != "HEAD"
    }
    assert found == {
        ("/assessments", "GET"),
        ("/candidates/{candidate_id}/assessment", "GET"),
        ("/candidates/{candidate_id}/assessment", "POST"),
        ("/candidates/{candidate_id}/assessment/report", "GET"),
    }
    for route in assessment_router.routes:
        calls = [dependency.call for dependency in route.dependant.dependencies]
        assert require_recruiter in calls


def test_only_a_submitted_quiz_becomes_an_input() -> None:
    attempt = McqAttempt(
        id=uuid4(),
        candidate_id=uuid4(),
        job_version_id=uuid4(),
        questions=[],
        answers=None,
        correct_count=None,
        score=80,
        time_limit_seconds=600,
        llm_tier="none",
        fallback_used=False,
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        submitted_at=None,
    )
    assert _mcq_input(attempt) is None
    assert _mcq_input(None) is None
    attempt.submitted_at = datetime.now(UTC)
    assert _mcq_input(attempt) == 80


def test_cv_and_interview_inputs_keep_their_citations() -> None:
    snapshot = ScoreSnapshot(
        id=uuid4(),
        candidate_id=uuid4(),
        job_version_id=uuid4(),
        aggregate_score=0.85,
        must_have_ratio=1,
        technical_score=0.88,
        experience_score=0.8,
        qualification_score=0.78,
        fairness_flags=[],
        justifications=[],
        llm_tier="none",
        fallback_used=False,
        rank=1,
        created_at=datetime.now(UTC),
    )
    snapshot.evaluations = [
        QueryEvaluation(
            id=uuid4(),
            snapshot_id=snapshot.id,
            query_id="Q1",
            status="met",
            confidence=0.9,
            evidence="Built REST APIs using FastAPI and PostgreSQL.",
            semantic_score=0.8,
        )
    ]
    cv = _cv_input(snapshot, {"Q1": "FastAPI experience"})
    assert cv is not None
    assert cv["evaluations"] == [
        {
            "query_id": "Q1",
            "question": "FastAPI experience",
            "status": "met",
            "evidence": "Built REST APIs using FastAPI and PostgreSQL.",
        }
    ]
    analysis = InterviewAnalysis(
        id=uuid4(),
        session_id=uuid4(),
        relevance=8.5,
        technical_accuracy=8.0,
        completeness=8.0,
        articulation=8.5,
        gaps=["Tool Calling (MCP)"],
        discrepancies=[],
        summary="Noted.",
        justifications=[],
        llm_tier="none",
        fallback_used=False,
        created_at=datetime.now(UTC),
    )
    analysis.pairs = [
        QAPair(
            id=uuid4(),
            analysis_id=analysis.id,
            pair_id="QA_01",
            sequence=1,
            question="How do you update the index?",
            answer="We re-embed document updates asynchronously.",
            intent="technical",
            start_time=18.0,
            end_time=19.0,
            citation="Transcript turn 18.0-19.0",
            query_ids=["Q1"],
            relevance=8.5,
            technical_accuracy=8.0,
            completeness=8.0,
            articulation=8.5,
            notes={},
        )
    ]
    qa = _qa_input(analysis)
    assert qa is not None
    assert qa["gaps"] == ["Tool Calling (MCP)"]
    assert qa["pairs"][0]["citation"] == "Transcript turn 18.0-19.0"
    assert _qa_input(None) is None


def test_key_gap_prefers_a_missing_input_over_a_weakness() -> None:
    assert key_gap_text([], [], assessed=False) == "Not assessed"
    assert key_gap_text(["Tool Calling (MCP)"], ["Thin Docker answer."], assessed=True) == "Tool Calling (MCP)"
    assert key_gap_text([], ["Thin Docker answer."], assessed=True) == "Thin Docker answer."
    assert key_gap_text([], [], assessed=True) == "None"


def test_report_html_keeps_the_citation_and_escapes_markup() -> None:
    report = AssessmentRead(
        candidate_id=uuid4(),
        full_name="Ada <script>",
        job_title="Platform engineer",
        overall_suitability="strong_fit",
        suitability_label="Strong Fit",
        overall_score=82.8,
        component_scores=ComponentScoresRead(
            cv_screening=85.0,
            mcq_quiz=80.0,
            interview_qa=82.5,
            technical_dimension=88.0,
            experience_dimension=80.0,
            qualification_dimension=78.0,
        ),
        strengths=["Candidate has strong FastAPI experience."],
        weaknesses=[],
        evidence_gaps=["Tool Calling (MCP)"],
        traceability=[
            {
                "claim": "Candidate has strong FastAPI experience.",
                "source_type": "cv",
                "source_reference": "Q1",
                "evidence": "Built REST APIs using FastAPI and PostgreSQL.",
            }
        ],
        narrative="Cited source Q1: Built REST APIs using FastAPI and PostgreSQL.",
        cv_weight=0.3,
        mcq_weight=0.2,
        interview_weight=0.5,
        llm_tier="claude",
        fallback_used=False,
        created_at=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
    )
    html = render_assessment_report(report)
    assert "Ada &lt;script&gt;" in html
    assert "<script>" not in html
    assert "Transcript" not in html or "Q1" in html
    assert "Built REST APIs using FastAPI and PostgreSQL." in html
    assert "82.8" in html
    assert "30%" in html
    assert "20%" in html
    assert "50%" in html
