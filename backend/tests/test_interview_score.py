import json

import pytest

from app.api.v1.interview_reports import router
from app.core.llm_fallback import FallbackLLMManager
from app.services.interview_score import (
    DIMENSIONS,
    ChecklistTopic,
    PerformanceDraft,
    SpeechTurn,
    conductor_label,
    draft_interview_score,
    score_interview,
)

FASTAPI = ChecklistTopic("Q1", "Have you used FastAPI in production?", "technical")
INDEXES = ChecklistTopic("Q2", "How do you design database indexes?", "technical")
TURNS = [
    SpeechTurn("recruiter", "Have you used FastAPI in production?"),
    SpeechTurn("candidate", "I used FastAPI in production for the payments service."),
    SpeechTurn("recruiter", "How do you design database indexes?"),
    SpeechTurn(
        "candidate",
        "First I checked the logs, then I fixed the query because the index was missing.",
    ),
]


class BoomProvider:
    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        raise AssertionError("a silent interview must not call the model")


class ScriptedProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        del prompt, system
        self.calls += 1
        return json.dumps(self.payload)


def _by_key(draft: PerformanceDraft) -> dict[str, float]:
    return {item.key: item.score for item in draft.dimensions}


def test_silent_interview_scores_zero_without_assuming_speech() -> None:
    draft = score_interview([], [FASTAPI, INDEXES])
    assert draft.overall_score == 0.0
    assert set(_by_key(draft)) == {key for key, _label in DIMENSIONS}
    assert all(item.score == 0.0 and item.evidence == "" for item in draft.dimensions)
    assert all(item.note == "No candidate speech was captured." for item in draft.dimensions)
    assert "CV" not in draft.summary


def test_interview_score_breaks_down_the_six_dimensions() -> None:
    draft = score_interview(TURNS, [FASTAPI, INDEXES])
    scores = _by_key(draft)
    assert scores == {
        "technical_competency": 50.0,
        "communication": 100.0,
        "relevance": 50.0,
        "problem_solving": 90.0,
        "experience_depth": 15.0,
        "job_alignment": 50.0,
    }
    assert draft.overall_score == round(sum(scores.values()) / len(scores), 1)
    speech = " ".join(turn.text for turn in TURNS if turn.speaker == "candidate")
    for item in draft.dimensions:
        assert item.evidence
        assert item.evidence in speech
    technical = next(item for item in draft.dimensions if item.key == "technical_competency")
    assert "FastAPI" in technical.evidence
    solving = next(item for item in draft.dimensions if item.key == "problem_solving")
    assert "because" in solving.evidence


def test_a_specific_example_raises_experience_depth() -> None:
    draft = score_interview(
        [SpeechTurn("candidate", "I shipped the billing service in 2019 and cut latency 40 percent.")],
        [],
    )
    experience = next(item for item in draft.dimensions if item.key == "experience_depth")
    assert experience.score == 35.0
    assert "2019" in experience.evidence


def test_a_checklist_year_count_is_not_treated_as_demonstrated_experience() -> None:
    draft = score_interview(
        [SpeechTurn("candidate", "I used FastAPI in production for the payments service.")],
        [ChecklistTopic("Q1", "Need 10 years of FastAPI experience.", "experience")],
    )
    experience = next(item for item in draft.dimensions if item.key == "experience_depth")
    assert experience.score == 15.0
    assert "10" not in experience.evidence


def test_invented_evidence_is_dropped() -> None:
    speech = "I used FastAPI in production for the payments service."
    draft = score_interview(
        [SpeechTurn("candidate", speech)],
        [FASTAPI],
        quotes={"technical_competency": "I invented a Kubernetes platform from scratch."},
    )
    technical = next(item for item in draft.dimensions if item.key == "technical_competency")
    assert "Kubernetes" not in technical.evidence
    assert technical.evidence in speech


def test_a_quote_the_candidate_said_is_kept() -> None:
    speech = "I used FastAPI in production for the payments service."
    draft = score_interview(
        [SpeechTurn("candidate", speech)],
        [FASTAPI],
        quotes={"technical_competency": speech},
    )
    technical = next(item for item in draft.dimensions if item.key == "technical_competency")
    assert technical.evidence in speech
    assert technical.evidence.startswith("I used FastAPI")


def test_score_fields_do_not_carry_a_cv_aggregate() -> None:
    assert "aggregate_score" not in PerformanceDraft.__dataclass_fields__
    assert "cv_score" not in PerformanceDraft.__dataclass_fields__
    assert "overall_suitability" not in PerformanceDraft.__dataclass_fields__


def test_conductor_label_names_both_hosts() -> None:
    assert conductor_label("agent") == "Agent"
    assert conductor_label("recruiter") == "Recruiter"
    assert conductor_label("") == "Recruiter"


def test_report_routes_are_registered() -> None:
    paths = {getattr(route, "path", "") for route in router.routes}
    assert "/interview-history" in paths
    assert "/candidates/{candidate_id}/interview-score" in paths
    assert "/candidates/{candidate_id}/interview-analysis" in paths


@pytest.mark.asyncio
async def test_silent_interview_does_not_call_the_model() -> None:
    draft = await draft_interview_score(FallbackLLMManager(BoomProvider(), BoomProvider(), BoomProvider()), [], [FASTAPI])
    assert draft.llm_tier == "none"
    assert draft.fallback_used is False
    assert draft.overall_score == 0.0


@pytest.mark.asyncio
async def test_model_quote_is_kept_only_when_it_was_said() -> None:
    speech = "I used FastAPI in production for the payments service."
    provider = ScriptedProvider(
        {
            "evidence": [
                {"key": "technical_competency", "quote": speech},
                {"key": "communication", "quote": "The candidate was unclear and should be rejected."},
            ]
        }
    )
    draft = await draft_interview_score(
        FallbackLLMManager(provider, provider, provider),
        [SpeechTurn("candidate", speech)],
        [FASTAPI],
    )
    assert provider.calls == 1
    by_evidence = {item.key: item.evidence for item in draft.dimensions}
    assert by_evidence["technical_competency"] in speech
    assert by_evidence["technical_competency"].startswith("I used FastAPI")
    assert "rejected" not in by_evidence["communication"]
    assert by_evidence["communication"] in speech
