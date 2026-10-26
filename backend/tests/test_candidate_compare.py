import json
from datetime import UTC, datetime
from uuid import uuid4

from app.core.llm_fallback import FallbackLLMManager
from app.models.candidate import (
    AssessmentStrength,
    AssessmentWeakness,
    Candidate,
    ConsolidatedAssessment,
    McqAttempt,
    ScoreSnapshot,
)
from app.models.job import Job, JobVersion
from app.services.candidate_compare import (
    COMPARE_SYSTEM,
    CompareFacts,
    narrative_from_model,
    narrative_from_scores,
    pair_error,
    profile_from_candidate,
    write_comparison,
)


class ScriptProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        assert system == COMPARE_SYSTEM
        assert "Ada Lovelace" in prompt
        assert "Ben Stone" in prompt
        return self.text


def _facts(
    name: str,
    *,
    job_id=None,
    candidate_id=None,
    cv: float | None = 0.82,
    overall: float | None = 82.0,
    interview: float | None = 74.0,
    quiz: int | None = 8,
    strengths: tuple[str, ...] = ("Ships careful APIs.",),
    gaps: tuple[str, ...] = ("Thin on testing.",),
) -> CompareFacts:
    return CompareFacts(
        candidate_id=candidate_id or uuid4(),
        full_name=name,
        job_id=job_id or uuid4(),
        job_title="Backend Engineer",
        rank=1,
        cv_score=cv,
        technical_score=0.80,
        experience_score=0.70,
        qualification_score=0.60,
        mcq_score=quiz,
        interview_score=interview,
        interview_note="I kept the handlers small.",
        overall_score=overall,
        suitability_label="Strong Fit",
        strengths=strengths,
        gaps=gaps,
    )


def test_same_role_is_required() -> None:
    left = _facts("Ada Lovelace")
    right = _facts("Ben Stone")
    problem = pair_error(left, right)
    assert problem is not None
    assert problem.code == "COMPARE_DIFFERENT_ROLES"
    shared = left.job_id
    same = pair_error(left, _facts("Ben Stone", job_id=shared))
    assert same is None
    duplicate = pair_error(left, _facts("Ada Lovelace", job_id=shared, candidate_id=left.candidate_id))
    assert duplicate is not None
    assert duplicate.code == "COMPARE_SAME_PERSON"


def test_score_narrative_uses_only_stored_numbers() -> None:
    job_id = uuid4()
    left = _facts("Ada Lovelace", job_id=job_id, overall=82.0)
    right = _facts("Ben Stone", job_id=job_id, overall=71.0, cv=0.64, strengths=("Clear examples.",), gaps=("Light on ownership.",))
    narrative = narrative_from_scores(left, right)
    assert narrative.source == "scores"
    assert "Ada Lovelace is ahead of Ben Stone" in narrative.summary
    assert "82.0" in narrative.summary
    assert "71.0" in narrative.summary
    assert "99" not in narrative.summary
    assert "Thin on testing." in narrative.tradeoff
    assert "Light on ownership." in narrative.tradeoff


def test_missing_scores_are_named_rather_than_filled_in() -> None:
    job_id = uuid4()
    left = _facts("Ada Lovelace", job_id=job_id, overall=None, cv=None, interview=None, quiz=None, strengths=(), gaps=())
    right = _facts("Ben Stone", job_id=job_id, overall=None, cv=0.64, interview=None, quiz=None, strengths=(), gaps=())
    narrative = narrative_from_scores(left, right)
    assert "not scored" in narrative.summary
    assert "Ada Lovelace" in narrative.summary
    assert "Ben Stone" in narrative.summary


def test_invented_number_falls_back_to_stored_scores() -> None:
    job_id = uuid4()
    left = _facts("Ada Lovelace", job_id=job_id)
    right = _facts("Ben Stone", job_id=job_id, overall=71.0)
    text = json.dumps(
        {
            "summary": "Ada Lovelace beats Ben Stone with a secret 99.",
            "left_edge": "Ada Lovelace leads.",
            "right_edge": "Ben Stone trails.",
            "tradeoff": "Pick Ada Lovelace.",
        }
    )
    parsed = narrative_from_model(text, left, right)
    assert parsed is None
    stored = narrative_from_scores(left, right)
    assert "99" not in stored.summary


def test_grounded_model_text_is_kept() -> None:
    job_id = uuid4()
    left = _facts("Ada Lovelace", job_id=job_id)
    right = _facts("Ben Stone", job_id=job_id, overall=71.0)
    text = json.dumps(
        {
            "summary": "Ada Lovelace is ahead of Ben Stone, 82.0 to 71.0.",
            "left_edge": "Ada Lovelace ships careful APIs.",
            "right_edge": "Ben Stone has a CV score of 0.82.",
            "tradeoff": "Ada Lovelace is thin on testing. Ben Stone is thin on testing.",
        }
    )
    parsed = narrative_from_model(text, left, right)
    assert parsed is not None
    assert parsed.source == "model"
    assert "82.0" in parsed.summary


async def test_rejected_model_text_uses_the_score_read() -> None:
    job_id = uuid4()
    left = _facts("Ada Lovelace", job_id=job_id)
    right = _facts("Ben Stone", job_id=job_id, overall=71.0)
    text = json.dumps(
        {
            "summary": "Ada Lovelace beats Ben Stone by 99 points.",
            "left_edge": "Ada Lovelace.",
            "right_edge": "Ben Stone.",
            "tradeoff": "Choose Ada Lovelace.",
        }
    )
    provider = ScriptProvider(text)
    narrative = await write_comparison(FallbackLLMManager(provider, provider, provider), left, right)
    assert narrative.source == "scores"
    assert "99" not in narrative.summary
    assert "82.0" in narrative.summary


def test_profile_ignores_an_unsubmitted_quiz() -> None:
    now = datetime.now(UTC)
    job = Job(id=uuid4(), title="Backend Engineer", mail_subject="Backend Engineer", created_at=now)
    version = JobVersion(
        id=uuid4(),
        job_id=job.id,
        version_number=1,
        status="locked",
        seniority="Mid-Level",
        required_skills=["Python"],
        preferred_skills=[],
        qualifications="Degree",
        minimum_years=2,
        technical_weight=0.5,
        experience_weight=0.3,
        qualification_weight=0.2,
        contract="Full Time",
        category="Information Technology",
        description="Build APIs.",
        policy_excerpts=[],
        llm_tier="claude",
        fallback_used=False,
        created_at=now,
    )
    version.job = job
    candidate = Candidate(
        id=uuid4(),
        job_version_id=version.id,
        email="ada@example.com",
        full_name="Ada Lovelace",
        content_sha256="a" * 64,
        source_message_id="msg-1",
        created_at=now,
    )
    candidate.version = version
    candidate.interview_session = None
    candidate.snapshot = ScoreSnapshot(
        id=uuid4(),
        candidate_id=candidate.id,
        job_version_id=version.id,
        aggregate_score=0.82,
        must_have_ratio=1.0,
        technical_score=0.8,
        experience_score=0.7,
        qualification_score=0.6,
        fairness_flags=[],
        justifications=[],
        llm_tier="claude",
        fallback_used=False,
        rank=1,
        created_at=now,
    )
    candidate.quiz_attempt = McqAttempt(
        id=uuid4(),
        candidate_id=candidate.id,
        job_version_id=version.id,
        questions=[],
        answers=None,
        correct_count=None,
        score=9,
        time_limit_seconds=600,
        llm_tier="claude",
        fallback_used=False,
        created_at=now,
        started_at=now,
        submitted_at=None,
    )
    assessment = ConsolidatedAssessment(
        id=uuid4(),
        candidate_id=candidate.id,
        job_version_id=version.id,
        overall_suitability="strong_fit",
        overall_score=82.0,
        narrative="Solid.",
        cv_weight=0.3,
        mcq_weight=0.2,
        interview_weight=0.5,
        llm_tier="claude",
        fallback_used=False,
        created_at=now,
    )
    assessment.strengths = [
        AssessmentStrength(id=uuid4(), assessment_id=assessment.id, sequence=1, text="Ships careful APIs."),
    ]
    assessment.weaknesses = [
        AssessmentWeakness(id=uuid4(), assessment_id=assessment.id, sequence=1, text="Thin on testing."),
    ]
    candidate.consolidated_assessment = assessment
    facts = profile_from_candidate(candidate)
    assert facts.mcq_score is None
    assert facts.cv_score == 0.82
    assert facts.overall_score == 82.0
    assert facts.suitability_label == "Strong Fit"
    assert facts.interview_score is None
    assert facts.strengths == ("Ships careful APIs.",)
    assert facts.gaps == ("Thin on testing.",)
    assert facts.job_title == "Backend Engineer"
