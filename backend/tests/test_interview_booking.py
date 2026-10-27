import uuid
from datetime import UTC, datetime

from app.core.config import Settings
from app.services.interview_booking import reserve_call
from app.services.invites import InviteSender
from app.services.schedule import BusyWindow, overlaps


class MemorySender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str, str]] = []
        self.html: list[str] = []

    def send(
        self,
        to_address: str,
        subject: str,
        body: str,
        *,
        html: str = "",
        attachment_ics: str = "",
    ) -> None:
        self.sent.append((to_address, subject, body, attachment_ics))
        self.html.append(html)


def _settings(**overrides: object) -> Settings:
    payload: dict[str, object] = {
        "_env_file": None,
        "company_name": "Sift",
        "invite_from_address": "jobs@sift.local",
        "apply_to_address": "recruiter@example.com",
        "interview_duration_minutes": 45,
        "interview_day_start_hour": 10,
        "interview_day_end_hour": 17,
        "interview_lead_minutes": 0,
        "interview_timezone": "Asia/Dhaka",
        "interview_weekdays": "0,1,2,3,4",
        "google_calendar_client_id": "",
        "google_calendar_client_secret": "",
        "google_calendar_refresh_token": "",
    }
    payload.update(overrides)
    return Settings(**payload)  # type: ignore[arg-type]


def test_two_shortlisted_calls_do_not_overlap_and_congratulate() -> None:
    settings = _settings()
    sender = MemorySender()
    now = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)
    first = reserve_call(
        settings,
        sender,
        candidate_name="Ada Lovelace",
        candidate_email="ada@example.com",
        job_title="Backend Engineer",
        url="http://localhost:3000/invite/ada",
        busy=[],
        now=now,
        candidate_id=uuid.uuid4(),
    )
    assert first is not None
    second = reserve_call(
        settings,
        sender,
        candidate_name="Grace Hopper",
        candidate_email="grace@example.com",
        job_title="Backend Engineer",
        url="http://localhost:3000/invite/grace",
        busy=[BusyWindow(first.start, first.end)],
        now=now,
        candidate_id=uuid.uuid4(),
    )
    assert second is not None
    assert first.end == second.start
    assert overlaps(first.start, first.end, [BusyWindow(second.start, second.end)]) is False
    ada = sender.sent[0]
    grace = sender.sent[2]
    assert ada[0] == "ada@example.com"
    assert ada[1].startswith("Congratulations")
    assert "Congratulations, Ada Lovelace." in ada[2]
    assert "http://localhost:3000/invite/ada" in ada[2]
    assert "score" not in ada[2].casefold()
    assert "rank" not in ada[2].casefold()
    assert "Join your video interview" in sender.html[0]
    assert "http://localhost:3000/invite/ada" in sender.html[0]
    assert "score" not in sender.html[0].casefold()
    assert "rank" not in sender.html[0].casefold()
    assert "METHOD:REQUEST" in ada[3]
    assert "DTSTART:20261021T040000Z" in ada[3]
    assert "DTSTART:20261021T044500Z" in grace[3]
    assert sender.sent[1][0] == "recruiter@example.com"
    assert sender.sent[1][1].startswith("Interview booked:")
    assert "METHOD:REQUEST" in sender.sent[1][3]


def test_a_closed_day_does_not_send_an_invite() -> None:
    sender = MemorySender()
    reserved = reserve_call(
        _settings(interview_day_start_hour=10, interview_day_end_hour=10),
        sender,
        candidate_name="Ada Lovelace",
        candidate_email="ada@example.com",
        job_title="Backend Engineer",
        url="http://localhost:3000/invite/ada",
        busy=[],
        now=datetime(2026, 10, 21, 2, 0, tzinfo=UTC),
        candidate_id=uuid.uuid4(),
    )
    assert reserved is None
    assert sender.sent == []


def test_sender_protocol_accepts_the_memory_sender() -> None:
    sender: InviteSender = MemorySender()
    sender.send("ada@example.com", "Hello", "Body")
