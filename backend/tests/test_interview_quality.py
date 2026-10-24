from app.api.v1.interview_reports import router
from app.services.interview_quality import (
    AnsweredQuestion,
    ChecklistTopic,
    QualityDraft,
    QualityTurn,
    assess_interview,
)

FASTAPI = ChecklistTopic("Q1", "Have you used FastAPI in production?")
INDEXES = ChecklistTopic("Q2", "How do you design database indexes?")
TURNS = [
    QualityTurn("recruiter", 0, 10, "Have you used FastAPI in production?"),
    QualityTurn("candidate", 10, 40, "I used FastAPI in production for the payments service last year."),
    QualityTurn("recruiter", 40, 50, "How do you design database indexes?"),
    QualityTurn("candidate", 50, 55, "Yes."),
]
LONG = "I used FastAPI in production for the payments service last year."


def _score(draft: QualityDraft, key: str) -> float | None:
    return next(item.score for item in draft.dimensions if item.key == key)


def test_silent_interview_does_not_judge_the_candidate() -> None:
    draft = assess_interview([], [FASTAPI, INDEXES])
    assert draft.overall_score == 0.0
    assert _score(draft, "process_consistency") is None
    assert any("No speech was captured" in item.text for item in draft.recommendations)
    assert "reject" not in draft.summary.casefold()
    assert "candidate score" not in draft.summary.casefold()


def test_process_review_names_a_weak_question_and_a_missed_competency() -> None:
    draft = assess_interview(TURNS, [FASTAPI, INDEXES])
    assert _score(draft, "question_effectiveness") == 50.0
    assert _score(draft, "competency_coverage") == 50.0
    assert _score(draft, "process_consistency") is None
    assert _score(draft, "interaction_quality") == 85.0
    assert draft.interviewer_share == 0.364
    assert draft.candidate_share == 0.636
    scored = [item.score for item in draft.dimensions if item.score is not None]
    assert draft.overall_score == round(sum(scored) / len(scored), 1)
    kinds = {item.kind for item in draft.recommendations}
    assert "unexplored" in kinds
    assert "low_signal" in kinds
    assert "speaking" not in kinds
    assert any("database indexes" in item.text for item in draft.recommendations)
    assert all("reject" not in item.text.casefold() for item in draft.recommendations)


def test_interviewer_monologue_asks_for_more_candidate_time() -> None:
    draft = assess_interview(
        [
            QualityTurn("recruiter", 0, 90, "Tell me about your recent production work in detail."),
            QualityTurn("candidate", 90, 100, "Yes."),
        ],
        [FASTAPI],
    )
    assert draft.interviewer_share == 0.9
    speaking = next(item for item in draft.recommendations if item.kind == "speaking")
    assert "Leave more time for the candidate." in speaking.text


def test_other_interviews_set_the_consistency_comparison() -> None:
    draft = assess_interview(TURNS[:2], [FASTAPI, INDEXES], peer_coverage=[{"Q1", "Q2"}])
    assert _score(draft, "process_consistency") == 50.0
    assert any(item.kind == "consistency" and "database indexes" in item.text for item in draft.recommendations)


def test_a_low_answer_score_is_little_signal_even_when_the_answer_is_long() -> None:
    draft = assess_interview(
        [],
        [FASTAPI],
        pairs=[
            AnsweredQuestion("Have you used FastAPI in production?", LONG, relevance=2, completeness=2, query_ids=("Q1",)),
            AnsweredQuestion("How do you design database indexes?", LONG, relevance=8, completeness=8, query_ids=("Q2",)),
        ],
    )
    assert _score(draft, "question_effectiveness") == 50.0
    assert any("FastAPI" in item.text and item.kind == "low_signal" for item in draft.recommendations)


def test_an_unanswered_fragment_is_not_coached() -> None:
    draft = assess_interview(
        [
            *TURNS[:2],
            QualityTurn("recruiter", 40, 44, "So there is a pen"),
            QualityTurn("recruiter", 44, 48, "Hello, I am interviewing you for the MinLab."),
        ],
        [FASTAPI],
    )
    text = " ".join(item.text for item in draft.recommendations)
    assert "pen" not in text.casefold()
    assert "MinLab" not in text


def test_an_audio_check_is_not_treated_as_a_weak_interview_question() -> None:
    draft = assess_interview(
        [
            QualityTurn("recruiter", 0, 5, "Can you hear me?"),
            QualityTurn("candidate", 5, 8, "Yes."),
            *TURNS,
        ],
        [FASTAPI, INDEXES],
    )
    assert all("hear me" not in item.text.casefold() for item in draft.recommendations)


def test_quality_fields_do_not_carry_a_candidate_score() -> None:
    assert "aggregate_score" not in QualityDraft.__dataclass_fields__
    assert "overall_suitability" not in QualityDraft.__dataclass_fields__


def test_quality_route_is_registered() -> None:
    paths = {getattr(route, "path", "") for route in router.routes}
    assert "/candidates/{candidate_id}/interview-quality" in paths
