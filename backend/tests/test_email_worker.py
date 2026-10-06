import uuid

from app.services.email_worker import match_job
from app.services.screening import JobMailKey


def _job(title: str, subject: str) -> JobMailKey:
    return JobMailKey(job_id=uuid.uuid4(), mail_subject=subject, version_id=uuid.uuid4(), title=title)


def test_subject_matches_saved_job_subject() -> None:
    engineer = _job("Senior Python Engineer", "Senior Python Engineer")
    designer = _job("Brand Designer", "Brand Designer")
    matched = match_job("Application: Senior Python Engineer", [designer, engineer])
    assert matched is engineer


def test_subject_matches_job_id() -> None:
    engineer = _job("Senior Python Engineer", "Senior Python Engineer")
    matched = match_job(f"CV attached {engineer.job_id}", [engineer])
    assert matched is engineer


def test_ambiguous_subjects_do_not_match() -> None:
    first = _job("Engineer", "Engineer")
    second = _job("Engineer", "Engineer")
    assert match_job("Engineer application", [first, second]) is None


def test_job_id_wins_when_another_title_also_matches() -> None:
    broad = _job("Engineer", "Engineer")
    specific = _job("Senior Python Engineer", "Senior Python Engineer")
    matched = match_job(f"Engineer {specific.job_id}", [broad, specific])
    assert matched is specific
