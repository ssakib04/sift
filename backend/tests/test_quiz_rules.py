import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.v1.quizzes import router
from app.models.candidate import Candidate, McqAttempt
from app.schemas.quiz import CandidateQuizRead, QuizPaper, QuizSubmitRequest, RecruiterQuizRead
from app.services.quiz_rules import (
    QUIZ_TIME_LIMIT_SECONDS,
    accept_answers,
    build_quiz_prompt,
    candidate_quiz_read,
    cv_excerpt,
    open_attempt,
    parse_quiz_paper,
    recruiter_quiz_read,
    score_answers,
    seconds_remaining,
    settle,
)
from app.services.screening import _to_candidate_read
from tests.checklist_factory import sample_queries


def _questions() -> list[dict[str, object]]:
    return [
        {
            "question_id": f"Q{index}",
            "query_id": f"Q{index}",
            "prompt": f"Which choice shows production skill number {index}?",
            "options": ["Alpha", "Beta", "Gamma", "Delta"],
            "correct_index": index % 4,
            "explanation": f"The keyed option for criterion {index} is the scored choice.",
        }
        for index in range(1, 11)
    ]


def _paper() -> QuizPaper:
    return QuizPaper.model_validate({"questions": _questions()})


def _keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(str(key))
            found.update(_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_keys(item))
    return found


def test_paper_requires_ten_distinct_checklist_questions() -> None:
    paper = _paper()
    assert [question.question_id for question in paper.questions] == [f"Q{index}" for index in range(1, 11)]
    broken = _questions()
    broken[0]["options"] = ["Alpha", "Alpha", "Gamma", "Delta"]
    with pytest.raises(ValidationError):
        QuizPaper.model_validate({"questions": broken})
    missing = _questions()[:-1]
    with pytest.raises(ValidationError):
        QuizPaper.model_validate({"questions": missing})


def test_fenced_model_json_becomes_a_paper() -> None:
    raw = "```json\n" + json.dumps({"questions": _questions()}) + "\n```"
    paper = parse_quiz_paper(raw)
    assert paper.questions[0].question_id == "Q1"


def test_score_is_ten_points_per_correct_answer() -> None:
    paper = _paper()
    perfect = tuple(question.correct_index for question in paper.questions)
    correct_count, score = score_answers(paper, perfect)
    assert correct_count == 10
    assert score == 100
    mixed = tuple(None if index < 2 else question.correct_index for index, question in enumerate(paper.questions))
    correct_count, score = score_answers(paper, mixed)
    assert correct_count == 8
    assert score == 80


def test_submit_window_scores_answers_and_then_locks_them() -> None:
    now = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    state = open_attempt(_paper(), now)
    assert seconds_remaining(state.started_at, now, state.time_limit_seconds) == QUIZ_TIME_LIMIT_SECONDS
    answers = tuple(0 for _ in range(10))
    submitted = accept_answers(state, answers, now + timedelta(seconds=610))
    assert submitted.score == 20
    assert submitted.submitted_at == now + timedelta(seconds=610)
    again = accept_answers(submitted, tuple(1 for _ in range(10)), now + timedelta(seconds=611))
    assert again.answers == answers
    assert again.score == 20


def test_a_late_quiz_closes_without_credit() -> None:
    now = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    state = open_attempt(_paper(), now)
    expired = settle(state, now + timedelta(seconds=616))
    assert expired.score == 0
    assert expired.answers == tuple(None for _ in range(10))
    view = candidate_quiz_read(expired, now + timedelta(seconds=616))
    assert view.status == "submitted"
    assert view.seconds_remaining == 0
    assert view.review is not None
    assert view.review[0].selected_index is None


def test_candidate_payload_hides_the_aggregate_score() -> None:
    now = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    state = open_attempt(_paper(), now)
    hidden = {"score", "correct_count", "rank", "llm_tier", "fallback_used", "correct_index", "explanation"}
    open_view = candidate_quiz_read(state, now)
    assert hidden.isdisjoint(_keys(open_view.model_dump()))
    answers = tuple(question.correct_index for question in state.paper.questions)
    submitted = accept_answers(state, answers, now)
    review = candidate_quiz_read(submitted, now).model_dump()
    assert "score" not in _keys(review)
    assert "correct_count" not in _keys(review)
    assert review["review"][0]["explanation"]
    assert review["review"][0]["correct_index"] == state.paper.questions[0].correct_index


def test_recruiter_payload_keeps_the_integer_score() -> None:
    now = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    candidate_id = uuid4()
    assert recruiter_quiz_read(candidate_id, None, now).status == "not_started"
    state = open_attempt(_paper(), now)
    assert recruiter_quiz_read(candidate_id, state, now).score is None
    submitted = accept_answers(state, tuple(0 for _ in range(10)), now)
    read = recruiter_quiz_read(candidate_id, submitted, now)
    assert read.score == 20
    assert read.correct_count == 2
    assert read.review[0].explanation


def test_candidate_route_model_has_no_score_field() -> None:
    paths = {getattr(route, "path", ""): getattr(route, "response_model", None) for route in router.routes}
    assert paths["/interview-sessions/{session_id}/quiz"] is CandidateQuizRead
    assert paths["/interview-sessions/{session_id}/quiz/submit"] is CandidateQuizRead
    assert "score" not in CandidateQuizRead.model_fields
    assert paths["/candidates/{candidate_id}/quiz"] is RecruiterQuizRead
    assert "score" in RecruiterQuizRead.model_fields


def test_prompt_uses_the_locked_checklist_and_a_bounded_cv() -> None:
    checklist = [
        {
            "query_id": str(item["query_id"]),
            "question": str(item["question"]),
            "dimension": str(item["dimension"]),
            "requirement_type": str(item["requirement_type"]),
            "scoring_rubric": str(item["scoring_rubric"]),
        }
        for item in sample_queries()
    ]
    prompt = build_quiz_prompt(job_title="Senior Python Engineer", checklist=checklist, cv_text="FastAPI " * 2000)
    assert "Senior Python Engineer" in prompt
    assert "Q10" in prompt
    assert len(cv_excerpt("FastAPI " * 2000)) == 3500
    with pytest.raises(ValidationError):
        QuizSubmitRequest.model_validate({"answers": [0, 1]})


def test_recruiter_candidate_read_shows_only_a_submitted_quiz_score() -> None:
    now = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    candidate = Candidate(
        id=uuid4(),
        job_version_id=uuid4(),
        email="ada@example.com",
        full_name="Ada Lovelace",
        content_sha256="abc",
        source_message_id="msg-1",
        created_at=now,
    )
    candidate.parse_result = None
    candidate.snapshot = None
    candidate.magic_link = None
    candidate.quiz_attempt = McqAttempt(
        id=uuid4(),
        candidate_id=candidate.id,
        job_version_id=candidate.job_version_id,
        questions=[],
        answers=[0] * 10,
        correct_count=8,
        score=80,
        time_limit_seconds=600,
        llm_tier="claude",
        fallback_used=False,
        created_at=now,
        started_at=now,
        submitted_at=now,
    )
    assert _to_candidate_read(candidate).mcq_score == 80
    candidate.quiz_attempt.submitted_at = None
    candidate.quiz_attempt.score = 80
    assert _to_candidate_read(candidate).mcq_score is None
