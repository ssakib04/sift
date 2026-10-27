import uuid
from datetime import UTC, datetime

import pytest

from app.schemas.final_ranking import ApprovalRequest
from app.services.final_ranking import (
    FinalRankError,
    FinishedPerson,
    approval_body,
    approval_html,
    mail_planned,
    order_finished,
    pipeline_complete,
    validate_approval_count,
)


class MemorySender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.html: list[str] = []
        self.fail_for: set[str] = set()

    def send(
        self,
        to_address: str,
        subject: str,
        body: str,
        *,
        html: str = "",
        attachment_ics: str = "",
    ) -> None:
        del attachment_ics
        if to_address in self.fail_for:
            raise RuntimeError("smtp down")
        self.sent.append((to_address, subject, body))
        self.html.append(html)


def _person(
    name: str,
    score: float,
    *,
    email: str = "",
    mailed: datetime | None = None,
) -> FinishedPerson:
    return FinishedPerson(
        candidate_id=uuid.uuid4(),
        full_name=name,
        email=email or f"{name.split()[0].lower()}@example.com",
        overall_score=score,
        suitability_label="Strong Fit",
        cv_score=0.8,
        interview_score=8.0,
        quiz_score=16,
        approval_mailed_at=mailed,
    )


def test_pipeline_complete_requires_every_stage() -> None:
    assert pipeline_complete(cv_scored=True, interview_ended=True, quiz_submitted=True, overall_score=81.0)
    assert not pipeline_complete(cv_scored=False, interview_ended=True, quiz_submitted=True, overall_score=81.0)
    assert not pipeline_complete(cv_scored=True, interview_ended=False, quiz_submitted=True, overall_score=81.0)
    assert not pipeline_complete(cv_scored=True, interview_ended=True, quiz_submitted=False, overall_score=81.0)
    assert not pipeline_complete(cv_scored=True, interview_ended=True, quiz_submitted=True, overall_score=None)


def test_final_order_uses_master_score_then_name() -> None:
    ada = _person("Ada Lovelace", 70.0)
    grace = _person("Grace Hopper", 91.0)
    alan = _person("Alan Turing", 91.0)
    ranked = order_finished([ada, grace, alan])
    assert [person.full_name for person in ranked] == ["Alan Turing", "Grace Hopper", "Ada Lovelace"]
    assert [person.rank for person in ranked] == [1, 2, 3]


def test_approval_count_is_the_recruiter_choice_within_the_finished_list() -> None:
    validate_approval_count(4, 1)
    validate_approval_count(4, 4)
    with pytest.raises(FinalRankError) as empty:
        validate_approval_count(0, 2)
    assert empty.value.code == "APPROVAL_EMPTY"
    with pytest.raises(FinalRankError) as too_many:
        validate_approval_count(2, 3)
    assert too_many.value.code == "APPROVAL_COUNT"
    assert "2" in too_many.value.message


def test_approval_request_rejects_zero() -> None:
    with pytest.raises(ValueError):
        ApprovalRequest(count=0)


def test_mail_goes_only_to_the_chosen_top_and_skips_people_already_approved() -> None:
    first = _person("Ada Lovelace", 90.0, mailed=datetime(2026, 10, 1, tzinfo=UTC))
    second = _person("Grace Hopper", 80.0)
    third = _person("Alan Turing", 70.0, email="  ")
    fourth = _person("Edsger Dijkstra", 60.0)
    ranked = order_finished([fourth, first, third, second])
    sender = MemorySender()
    mailed, skipped = mail_planned(
        ranked,
        3,
        sender,
        job_title="Backend Engineer",
        company_name="Sift",
        now=datetime(2026, 10, 27, tzinfo=UTC),
    )
    assert [person.full_name for person in mailed] == ["Grace Hopper"]
    assert [item.reason for item in skipped] == ["already_mailed", "missing_email"]
    assert sender.sent[0][0] == "grace@example.com"
    assert "Backend Engineer" in sender.sent[0][1]
    assert "Dear Grace Hopper," in sender.sent[0][2]
    assert "approved" in sender.sent[0][2]
    assert "Approval to proceed" in sender.html[0]
    assert "Grace Hopper" in sender.html[0]
    assert fourth.approval_mailed_at is None


def test_a_failed_mail_does_not_mark_that_person_approved() -> None:
    person = _person("Grace Hopper", 88.0)
    ranked = order_finished([person])
    sender = MemorySender()
    sender.fail_for.add(person.email)
    mailed, skipped = mail_planned(
        ranked,
        1,
        sender,
        job_title="Backend Engineer",
        company_name="Sift",
        now=datetime(2026, 10, 27, tzinfo=UTC),
    )
    assert mailed == []
    assert skipped[0].reason == "mail_failed"
    assert person.approval_mailed_at is None


def test_approval_body_reads_as_a_letter() -> None:
    body = approval_body(candidate_name="Ada Lovelace", job_title="Backend Engineer", company_name="Sift")
    assert body.startswith("Dear Ada Lovelace,")
    assert "Backend Engineer" in body
    assert "Sift" in body
    assert "approved" in body
    assert "video interview" in body
    assert "written assessment" in body
    assert "Warm regards," in body


def test_approval_html_is_a_letter() -> None:
    document = approval_html(candidate_name="Ada Lovelace", job_title="Backend Engineer", company_name="Sift")
    assert "Dear Ada Lovelace," in document
    assert "Approval to proceed" in document
    assert "Backend Engineer" in document
    assert "approved" in document
    assert "Sift" in document
