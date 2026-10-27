"""Book a shortlisted interview on the recruiter calendar and the applicant's."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.candidate import InterviewSession
from app.services.calendar import CalendarDraft, CalendarError, CreatedEvent, GoogleCalendarClient, build_ics
from app.services.invites import InviteSender, invitation_body, invitation_html
from app.services.schedule import (
    BusyWindow,
    ScheduleError,
    SlotRules,
    format_schedule_sentence,
    interview_zone,
    next_slot,
    parse_weekdays,
)

logger = logging.getLogger(__name__)

GOOGLE_CALENDAR_LINE = (
    "This time is on our Google Calendar, and Google is sending you an invitation for yours."
)
ICS_CALENDAR_LINE = (
    "A calendar invitation is attached. Accept it to place this interview on your Google Calendar. "
    "The same time is held on ours."
)


@dataclass(frozen=True)
class ReservedCall:
    start: datetime
    end: datetime
    event_id: str
    calendar_url: str


def slot_rules(settings: Settings) -> SlotRules:
    duration_minutes = settings.interview_duration_minutes if settings.interview_duration_minutes >= 15 else 45
    return SlotRules(
        duration=timedelta(minutes=duration_minutes),
        zone=interview_zone(settings.interview_timezone),
        day_start_hour=min(max(settings.interview_day_start_hour, 0), 23),
        day_end_hour=min(max(settings.interview_day_end_hour, 1), 23),
        weekdays=parse_weekdays(settings.interview_weekdays),
        lead=timedelta(minutes=max(settings.interview_lead_minutes, 0)),
    )


def recruiter_calendar_address(settings: Settings) -> str:
    chosen = settings.recruiter_calendar_email.strip() or settings.apply_to_address.strip()
    return chosen


async def taken_windows(session: AsyncSession, now: datetime) -> list[BusyWindow]:
    """Interview windows already stored, including ones that are still underway."""
    rows = (
        await session.execute(
            select(InterviewSession.scheduled_start, InterviewSession.scheduled_end).where(
                InterviewSession.scheduled_end.is_not(None),
                InterviewSession.scheduled_end > now,
            )
        )
    ).all()
    windows: list[BusyWindow] = []
    for start, end in rows:
        if start is None or end is None:
            continue
        windows.append(BusyWindow(start=start, end=end))
    return windows


def remote_busy(client: GoogleCalendarClient, now: datetime) -> list[BusyWindow]:
    if not client.configured:
        return []
    try:
        return client.busy_windows(now, now + timedelta(days=21))
    except CalendarError:
        logger.warning("google_calendar_busy_unavailable")
        return []


def reserve_call(
    settings: Settings,
    sender: InviteSender,
    *,
    candidate_name: str,
    candidate_email: str,
    job_title: str,
    url: str,
    busy: list[BusyWindow],
    now: datetime,
    candidate_id: uuid.UUID,
    calendar: GoogleCalendarClient | None = None,
) -> ReservedCall | None:
    """Send the congratulations and hold the first free slot. None means the calendar is full."""
    rules = slot_rules(settings)
    try:
        start, end = next_slot(now, busy, rules)
    except ScheduleError as exc:
        logger.warning("interview_slot_unavailable reason=%s", exc)
        return None
    when_label = format_schedule_sentence(start, end, rules.zone)
    draft = _draft(
        settings,
        candidate_name=candidate_name,
        candidate_email=candidate_email,
        job_title=job_title,
        url=url,
        start=start,
        end=end,
        zone_name=rules.zone.key,
        candidate_id=candidate_id,
    )
    client = calendar or GoogleCalendarClient(settings)
    created = _place_on_google(client, draft)
    if created is None:
        ics = build_ics(draft, now=now)
        calendar_line = ICS_CALENDAR_LINE
        event_id = draft.uid
        calendar_url = ""
    else:
        ics = ""
        calendar_line = GOOGLE_CALENDAR_LINE
        event_id = created.event_id
        calendar_url = created.html_link
    sender.send(
        candidate_email,
        f"Congratulations — your interview for {job_title}",
        invitation_body(
            candidate_name=candidate_name,
            job_title=job_title,
            company_name=settings.company_name,
            url=url,
            when_label=when_label,
            calendar_line=calendar_line,
        ),
        html=invitation_html(
            candidate_name=candidate_name,
            job_title=job_title,
            company_name=settings.company_name,
            url=url,
            when_label=when_label,
            calendar_line=calendar_line,
        ),
        attachment_ics=ics,
    )
    if created is None:
        _mail_recruiter(
            settings,
            sender,
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            job_title=job_title,
            when_label=when_label,
            ics=ics,
        )
    return ReservedCall(start=start, end=end, event_id=event_id, calendar_url=calendar_url)


def _draft(
    settings: Settings,
    *,
    candidate_name: str,
    candidate_email: str,
    job_title: str,
    url: str,
    start: datetime,
    end: datetime,
    zone_name: str,
    candidate_id: uuid.UUID,
) -> CalendarDraft:
    organizer = settings.invite_from_address.strip()
    if "@" not in organizer:
        organizer = "jobs@sift.local"
    summary = f"Interview: {job_title}"
    description = (
        f"Congratulations. You have been selected to interview for {job_title} at {settings.company_name}.\n"
        f"Open your interview:\n{url}"
    )
    return CalendarDraft(
        start=start,
        end=end,
        summary=summary,
        description=description,
        attendee_email=candidate_email,
        attendee_name=candidate_name.strip() or candidate_email,
        organizer_email=organizer,
        organizer_name=settings.company_name.strip() or "Sift",
        uid=f"sift-interview-{candidate_id}@sift",
        zone_name=zone_name,
    )


def _place_on_google(client: GoogleCalendarClient, draft: CalendarDraft) -> CreatedEvent | None:
    if not client.configured:
        return None
    try:
        return client.create_event(draft)
    except CalendarError:
        logger.warning("google_calendar_event_unavailable")
        return None


def _mail_recruiter(
    settings: Settings,
    sender: InviteSender,
    *,
    candidate_name: str,
    candidate_email: str,
    job_title: str,
    when_label: str,
    ics: str,
) -> None:
    address = recruiter_calendar_address(settings)
    if "@" not in address or address.casefold() == candidate_email.casefold():
        return
    who = candidate_name.strip() or candidate_email
    try:
        sender.send(
            address,
            f"Interview booked: {who} for {job_title}",
            (
                f"{who} is booked for {job_title} on {when_label}.\n\n"
                "The calendar file is attached so this interview can sit on your Google Calendar. "
                "Their invitation already went out.\n"
            ),
            attachment_ics=ics,
        )
    except Exception:
        logger.warning("recruiter_calendar_mail_failed")
