from datetime import UTC, datetime
from uuid import uuid4

from app.services.interview_agenda import AgendaRow, group_scheduled_interviews, interview_status_label


def _row(
    title: str,
    name: str,
    start: datetime,
    *,
    job_id=None,
    status: str = "invited",
) -> AgendaRow:
    return AgendaRow(
        session_id=uuid4(),
        candidate_id=uuid4(),
        full_name=name,
        job_id=job_id or uuid4(),
        job_title=title,
        status=status,
        scheduled_start=start,
        schedule_label=start.isoformat(),
    )


def test_unscheduled_roles_are_left_off_the_agenda() -> None:
    dancer = uuid4()
    when = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    roles = group_scheduled_interviews([_row("Dancer", "Shafat", when, job_id=dancer)])
    assert [role.job_title for role in roles] == ["Dancer"]
    assert roles[0].interviews[0].full_name == "Shafat"
    assert roles[0].interviews[0].status == "Scheduled"


def test_interviews_are_grouped_by_role_and_time() -> None:
    dancer = uuid4()
    seller = uuid4()
    early = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    later = datetime(2026, 11, 3, 11, 0, tzinfo=UTC)
    roles = group_scheduled_interviews(
        [
            _row("Salesperson", "Shafat", later, job_id=seller, status="started"),
            _row("Dancer", "Ada", later, job_id=dancer),
            _row("Dancer", "Bea", early, job_id=dancer, status="ended"),
        ]
    )
    assert [role.job_title for role in roles] == ["Dancer", "Salesperson"]
    assert [item.full_name for item in roles[0].interviews] == ["Bea", "Ada"]
    assert roles[0].interviews[0].status == "Ended"
    assert roles[1].interviews[0].status == "In progress"


def test_blank_status_still_reads_as_scheduled() -> None:
    assert interview_status_label("") == "Scheduled"
    assert interview_status_label("invited") == "Scheduled"
