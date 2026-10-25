import pytest

from app.services.report_progress import (
    advance_report_progress,
    initial_report_progress,
    reports_still_writing,
    visible_report_progress,
)


def test_a_finished_interview_starts_every_report_as_pending() -> None:
    progress = initial_report_progress()
    assert set(progress) == {"qa", "claims", "score", "quality", "assessment"}
    assert reports_still_writing(progress) is True
    assert visible_report_progress("ended", progress)["score"] == "pending"
    assert visible_report_progress("invited", progress) == {}


def test_each_finished_report_stays_visible_after_leaving_the_page() -> None:
    progress = advance_report_progress(initial_report_progress(), "qa", "ready")
    progress = advance_report_progress(progress, "score", "failed")
    assert progress["qa"] == "ready"
    assert progress["claims"] == "pending"
    assert reports_still_writing(progress) is True
    done = advance_report_progress(progress, "claims", "ready")
    done = advance_report_progress(done, "quality", "ready")
    done = advance_report_progress(done, "assessment", "ready")
    assert reports_still_writing(done) is False
    assert visible_report_progress("ended", done)["score"] == "failed"


def test_an_unknown_report_step_is_rejected() -> None:
    with pytest.raises(ValueError):
        advance_report_progress(initial_report_progress(), "quiz", "ready")
