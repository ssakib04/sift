import uuid
from datetime import UTC, datetime

from app.services.email_worker import match_job
from app.services.screening import JobMailKey


def _job(title: str, subject: str, locked_at: datetime | None = None) -> JobMailKey:
    return JobMailKey(
        job_id=uuid.uuid4(),
        mail_subject=subject,
        version_id=uuid.uuid4(),
        title=title,
        locked_at=locked_at or datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_subject_matches_saved_job_subject() -> None:
    engineer = _job("Senior Python Engineer", "Senior Python Engineer")
    designer = _job("Brand Designer", "Brand Designer")
    matched = match_job("Application: Senior Python Engineer", [designer, engineer])
    assert matched is engineer


def test_subject_matches_job_id() -> None:
    engineer = _job("Senior Python Engineer", "Senior Python Engineer")
    matched = match_job(f"CV attached {engineer.job_id}", [engineer])
    assert matched is engineer


def test_duplicate_subjects_use_the_newest_locked_job() -> None:
    older = _job("Engineer", "Engineer", datetime(2026, 1, 1, tzinfo=UTC))
    newer = _job("Engineer", "Engineer", datetime(2026, 10, 7, tzinfo=UTC))
    assert match_job("Engineer application", [older, newer]) is newer


def test_job_id_wins_when_another_title_also_matches() -> None:
    broad = _job("Engineer", "Engineer")
    specific = _job("Senior Python Engineer", "Senior Python Engineer")
    matched = match_job(f"Engineer {specific.job_id}", [broad, specific])
    assert matched is specific
