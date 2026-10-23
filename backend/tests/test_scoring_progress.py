from datetime import UTC, datetime, timedelta

from app.services.scoring_progress import STALE_AFTER, present_progress, progress_label


def test_the_bar_names_each_phase() -> None:
    assert progress_label("scanning", 0, 0, 0) == "Checking the mailbox…"
    assert progress_label("scoring", 4, 12, 3) == "Scored 4 of 12"
    assert progress_label("complete", 0, 0, 0) == "No new CVs."
    assert progress_label("complete", 2, 2, 0) == "Scoring finished. None of the CVs could be scored."
    assert progress_label("complete", 1, 1, 1) == "1 CV scored. Choose who to invite from the ranking."
    assert progress_label("complete", 12, 12, 12) == "12 CVs scored. Choose who to invite from the ranking."
    assert progress_label("idle", 0, 0, 0) == ""


def test_a_stale_run_drops_off_the_bar() -> None:
    now = datetime(2026, 10, 23, tzinfo=UTC)
    fresh = present_progress("scoring", 12, 4, 4, updated_at=now, now=now)
    assert fresh.phase == "scoring"
    assert fresh.label == "Scored 4 of 12"
    stale = present_progress("scoring", 12, 4, 4, updated_at=now - STALE_AFTER - timedelta(seconds=1), now=now)
    assert stale.phase == "idle"
    assert stale.label == ""
