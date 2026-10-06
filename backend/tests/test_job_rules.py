import pytest

from app.services.job_rules import ChecklistLockedError, ensure_can_open_version, ensure_editable


def test_draft_checklist_can_be_edited() -> None:
    ensure_editable("draft")


def test_locked_checklist_cannot_be_edited() -> None:
    with pytest.raises(ChecklistLockedError):
        ensure_editable("locked")


def test_next_version_requires_a_locked_checklist() -> None:
    ensure_can_open_version("locked")
    with pytest.raises(ChecklistLockedError):
        ensure_can_open_version("draft")
