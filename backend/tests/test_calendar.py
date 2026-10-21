from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.services.calendar import CalendarDraft, CalendarError, GoogleCalendarClient, build_ics
from app.services.schedule import BusyWindow


def _draft() -> CalendarDraft:
    return CalendarDraft(
        start=datetime(2026, 10, 21, 4, 0, tzinfo=UTC),
        end=datetime(2026, 10, 21, 4, 45, tzinfo=UTC),
        summary="Interview: Backend Engineer",
        description="Open your interview:\nhttp://localhost:3000/invite/abc",
        attendee_email="ada@example.com",
        attendee_name="Ada Lovelace",
        organizer_email="jobs@sift.local",
        organizer_name="Sift",
        uid="sift-interview-ada@sift",
        zone_name="Asia/Dhaka",
    )


def test_ics_is_a_request_the_applicant_can_accept() -> None:
    ics = build_ics(_draft(), now=datetime(2026, 10, 21, 1, 0, tzinfo=UTC))
    assert "METHOD:REQUEST" in ics
    assert "ATTENDEE" in ics
    assert "MAILTO:ada@example.com" in ics
    assert "DTSTART:20261021T040000Z" in ics
    assert "DTEND:20261021T044500Z" in ics
    assert "score" not in ics.casefold()
    assert "rank" not in ics.casefold()


def test_google_event_invites_the_applicant_and_reads_busy_time() -> None:
    calls: list[str] = []

    def poster(
        url: str,
        *,
        data: dict[str, str] | None,
        json_body: dict[str, object] | None,
        headers: dict[str, str],
        params: dict[str, str] | None,
    ) -> dict[str, object]:
        calls.append(url)
        if url.endswith("/token"):
            assert data is not None
            assert data["grant_type"] == "refresh_token"
            return {"access_token": "ya29-test"}
        if url.endswith("/freeBusy"):
            assert headers["Authorization"] == "Bearer ya29-test"
            return {
                "calendars": {
                    "primary": {
                        "busy": [{"start": "2026-10-21T04:00:00Z", "end": "2026-10-21T04:45:00Z"}]
                    }
                }
            }
        assert params is not None
        assert params["sendUpdates"] == "all"
        assert json_body is not None
        attendees = json_body["attendees"]
        assert isinstance(attendees, list)
        assert attendees[0]["email"] == "ada@example.com"
        return {"id": "evt-1", "htmlLink": "https://calendar.google.com/event?eid=evt-1"}

    settings = Settings(
        _env_file=None,
        google_calendar_client_id="client",
        google_calendar_client_secret="secret",
        google_calendar_refresh_token="refresh",
        google_calendar_id="primary",
    )
    client = GoogleCalendarClient(settings, poster)
    busy = client.busy_windows(
        datetime(2026, 10, 21, 0, 0, tzinfo=UTC),
        datetime(2026, 11, 11, 0, 0, tzinfo=UTC),
    )
    created = client.create_event(_draft())
    assert busy == [
        BusyWindow(
            datetime(2026, 10, 21, 4, 0, tzinfo=UTC),
            datetime(2026, 10, 21, 4, 45, tzinfo=UTC),
        )
    ]
    assert created.event_id == "evt-1"
    assert created.html_link.startswith("https://calendar.google.com/")
    assert calls[0].endswith("/token")
    assert "/freeBusy" in calls[1]
    assert calls[2].endswith("/events")


def test_missing_google_credentials_do_not_call_google() -> None:
    def poster(
        url: str,
        *,
        data: dict[str, str] | None,
        json_body: dict[str, object] | None,
        headers: dict[str, str],
        params: dict[str, str] | None,
    ) -> dict[str, object]:
        raise AssertionError(url)

    client = GoogleCalendarClient(Settings(_env_file=None), poster)
    assert client.configured is False
    assert client.busy_windows(datetime.now(UTC), datetime.now(UTC)) == []
    with pytest.raises(CalendarError):
        client.create_event(_draft())
