from uuid import uuid4

import pytest

from app.core.database import SessionFactory, engine
from app.schemas.progress import ProgressStage
from app.services.interview_practice import PRACTICE_MAIL_SUBJECT
from app.services.progress import (
    STAGE_ORDER,
    ApplicantSignals,
    board_from_signals,
    list_progress,
    progress_stage,
    role_on_board,
)


def _signals(**overrides: object) -> ApplicantSignals:
    payload: dict[str, object] = {
        "candidate_id": uuid4(),
        "full_name": "Priya Shah",
        "rank": None,
        "aggregate_score": None,
        "invited": False,
        "interview_status": None,
        "quiz_submitted": False,
        "quiz_score": None,
        "assessed": False,
        "overall_score": None,
    }
    payload.update(overrides)
    return ApplicantSignals(**payload)  # type: ignore[arg-type]


def test_received_until_rank_and_score_both_exist() -> None:
    assert progress_stage(_signals()) == "received"
    assert progress_stage(_signals(aggregate_score=0.8)) == "received"
    assert progress_stage(_signals(rank=1, aggregate_score=0.82)) == "screened"


def test_later_stages_replace_earlier_ones() -> None:
    screened = _signals(rank=2, aggregate_score=0.4, invited=True)
    assert progress_stage(screened) == "invited"
    assert progress_stage(_signals(interview_status="invited")) == "invited"
    assert progress_stage(_signals(invited=True, interview_status="started")) == "interview"
    assert progress_stage(_signals(invited=True, interview_status="ended")) == "interview"
    assert progress_stage(_signals(interview_status="ended", quiz_submitted=True, quiz_score=0)) == "quiz"
    assert progress_stage(_signals(quiz_submitted=True, quiz_score=18, assessed=True, overall_score=81.0)) == "assessed"


def test_board_keeps_one_column_per_stage_and_sorts_by_rank() -> None:
    job_id = uuid4()
    first = _signals(full_name="Omar Ali", rank=2, aggregate_score=0.4)
    second = _signals(full_name="Priya Shah", rank=1, aggregate_score=0.9)
    waiting = _signals(full_name="Lina Roy")
    board = board_from_signals(job_id, "Senior Python Engineer", [first, second, waiting])
    assert board.applicant_count == 3
    assert [column.stage for column in board.columns] == list(STAGE_ORDER)
    screened = next(column for column in board.columns if column.stage == "screened")
    assert [card.full_name for card in screened.cards] == ["Priya Shah", "Omar Ali"]
    assert screened.cards[0].detail == "Rank #1"
    received = next(column for column in board.columns if column.stage == "received")
    assert received.cards[0].detail == "CV received"
    invited = board_from_signals(
        job_id,
        "Senior Python Engineer",
        [_signals(full_name="Ada Lovelace", invited=True, schedule_label="Wed 22 Oct, 10:00–10:45 (Asia/Dhaka)")],
    )
    invited_column = next(column for column in invited.columns if column.stage == "invited")
    assert invited_column.cards[0].detail == "Wed 22 Oct, 10:00–10:45 (Asia/Dhaka)"
    assert all(column.cards == [] for column in board.columns if column.stage not in {"screened", "received"})


def test_empty_role_still_has_every_column() -> None:
    board = board_from_signals(uuid4(), "Support Engineer", [])
    assert board.applicant_count == 0
    assert [column.label for column in board.columns] == [
        "Received",
        "Screened",
        "Invited",
        "Interview",
        "Quiz",
        "Assessed",
    ]


def test_practice_mailbox_is_not_a_progress_role() -> None:
    assert role_on_board(PRACTICE_MAIL_SUBJECT) is False
    assert role_on_board("Senior Python Engineer") is True


def test_quiz_and_assessment_details() -> None:
    quiz_stage: ProgressStage = progress_stage(_signals(quiz_submitted=True, quiz_score=0))
    assert quiz_stage == "quiz"
    board = board_from_signals(
        uuid4(),
        "Data Analyst",
        [
            _signals(full_name="Lina Roy", quiz_submitted=True, quiz_score=0),
            _signals(full_name="Noah Khan", assessed=True, overall_score=76.4, rank=1, aggregate_score=0.7),
        ],
    )
    quiz = next(column for column in board.columns if column.stage == "quiz")
    assessed = next(column for column in board.columns if column.stage == "assessed")
    assert quiz.cards[0].detail == "Quiz 0"
    assert assessed.cards[0].detail == "Overall 76.4"


@pytest.mark.asyncio
async def test_list_progress_reads_each_role() -> None:
    try:
        async with SessionFactory() as session:
            await session.connection()
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL is not available: {exc}")
    try:
        async with SessionFactory() as session:
            boards = await list_progress(session)
        assert isinstance(boards, list)
        for board in boards:
            assert [column.stage for column in board.columns] == list(STAGE_ORDER)
    finally:
        await engine.dispose()
