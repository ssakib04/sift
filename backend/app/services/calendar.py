"""Place an interview on Google Calendar, and build the invite file applicants can accept."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.services.schedule import BusyWindow, aware

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CALENDAR_URL = "https://www.googleapis.com/calendar/v3"


class CalendarError(Exception):
    """Google Calendar refused the request or returned a response we cannot use."""


@dataclass(frozen=True)
class CalendarDraft:
    start: datetime
    end: datetime
    summary: str
    description: str
    attendee_email: str
    attendee_name: str
    organizer_email: str
    organizer_name: str
    uid: str
    zone_name: str


@dataclass(frozen=True)
class CreatedEvent:
    event_id: str
    html_link: str


class CalendarPoster(Protocol):
    def __call__(
        self,
        url: str,
        *,
        data: dict[str, str] | None,
        json_body: dict[str, object] | None,
        headers: dict[str, str],
        params: dict[str, str] | None,
    ) -> dict[str, object]:
        """POST one Google request and return the JSON object."""


def _httpx_post(
    url: str,
    *,
    data: dict[str, str] | None,
    json_body: dict[str, object] | None,
    headers: dict[str, str],
    params: dict[str, str] | None,
) -> dict[str, object]:
    try:
        response = httpx.post(url, data=data, json=json_body, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CalendarError(type(exc).__name__) from exc
    if not isinstance(payload, dict):
        raise CalendarError("response")
    return payload


def _ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def _fold(line: str) -> str:
    if len(line.encode("utf-8")) <= 75:
        return line
    chunks: list[str] = []
    current = ""
    limit = 75
    for char in line:
        piece = current + char
        if current and len(piece.encode("utf-8")) > limit:
            chunks.append(current)
            current = char
            limit = 74
        else:
            current = piece
    if current:
        chunks.append(current)
    folded = chunks[0]
    for chunk in chunks[1:]:
        folded += "\r\n " + chunk
    return folded


def _stamp(value: datetime) -> str:
    return aware(value).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_ics(draft: CalendarDraft, *, now: datetime) -> str:
    """RFC 5545 request the applicant can add to Google Calendar."""
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//Sift//Interview//EN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{draft.uid}",
        f"DTSTAMP:{_stamp(now)}",
        f"DTSTART:{_stamp(draft.start)}",
        f"DTEND:{_stamp(draft.end)}",
        f"SUMMARY:{_ics_text(draft.summary)}",
        f"DESCRIPTION:{_ics_text(draft.description)}",
        f"ORGANIZER;CN={_ics_text(draft.organizer_name)}:MAILTO:{draft.organizer_email}",
        (
            f"ATTENDEE;CN={_ics_text(draft.attendee_name)};RSVP=TRUE;"
            f"PARTSTAT=NEEDS-ACTION;ROLE=REQ-PARTICIPANT:MAILTO:{draft.attendee_email}"
        ),
        "LOCATION:Sift video interview",
        "STATUS:CONFIRMED",
        "SEQUENCE:0",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _parse_google_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return aware(parsed)


class GoogleCalendarClient:
    """Recruiter calendar via the Google Calendar REST API. Empty credentials mean it stays quiet."""

    def __init__(self, settings: Settings, poster: CalendarPoster | None = None) -> None:
        self._settings = settings
        self._post: CalendarPoster = poster or _httpx_post
        self._access_token = ""

    @property
    def configured(self) -> bool:
        return bool(
            self._settings.google_calendar_client_id.strip()
            and self._settings.google_calendar_client_secret.strip()
            and self._settings.google_calendar_refresh_token.strip()
        )

    def busy_windows(self, start: datetime, end: datetime) -> list[BusyWindow]:
        if not self.configured:
            return []
        payload = self._authorized(
            f"{_CALENDAR_URL}/freeBusy",
            json_body={
                "timeMin": aware(start).isoformat(),
                "timeMax": aware(end).isoformat(),
                "items": [{"id": self._calendar_id()}],
            },
        )
        calendars = payload.get("calendars")
        if not isinstance(calendars, dict):
            raise CalendarError("freebusy")
        entry = calendars.get(self._calendar_id())
        if not isinstance(entry, dict):
            raise CalendarError("freebusy")
        raw_busy = entry.get("busy")
        if not isinstance(raw_busy, list):
            return []
        windows: list[BusyWindow] = []
        for item in raw_busy:
            if not isinstance(item, dict):
                continue
            window_start = _parse_google_time(item.get("start"))
            window_end = _parse_google_time(item.get("end"))
            if window_start is None or window_end is None:
                continue
            windows.append(BusyWindow(start=window_start, end=window_end))
        return windows

    def create_event(self, draft: CalendarDraft) -> CreatedEvent:
        if not self.configured:
            raise CalendarError("unconfigured")
        calendar_id = quote(self._calendar_id(), safe="")
        payload = self._authorized(
            f"{_CALENDAR_URL}/calendars/{calendar_id}/events",
            json_body={
                "summary": draft.summary,
                "description": draft.description,
                "start": {"dateTime": aware(draft.start).isoformat(), "timeZone": draft.zone_name},
                "end": {"dateTime": aware(draft.end).isoformat(), "timeZone": draft.zone_name},
                "attendees": [
                    {
                        "email": draft.attendee_email,
                        "displayName": draft.attendee_name or draft.attendee_email,
                    }
                ],
                "reminders": {"useDefault": True},
            },
            params={"sendUpdates": "all"},
        )
        event_id = payload.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise CalendarError("event")
        link = payload.get("htmlLink")
        return CreatedEvent(event_id=event_id, html_link=link if isinstance(link, str) else "")

    def _calendar_id(self) -> str:
        return self._settings.google_calendar_id.strip() or "primary"

    def _authorized(
        self,
        url: str,
        *,
        json_body: dict[str, object],
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {self._token()}"}
        return self._post(url, data=None, json_body=json_body, headers=headers, params=params)

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        payload = self._post(
            _TOKEN_URL,
            data={
                "client_id": self._settings.google_calendar_client_id.strip(),
                "client_secret": self._settings.google_calendar_client_secret.strip(),
                "refresh_token": self._settings.google_calendar_refresh_token.strip(),
                "grant_type": "refresh_token",
            },
            json_body=None,
            headers={},
            params=None,
        )
        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise CalendarError("token")
        self._access_token = token
        return token
