"""Find a free interview window that does not overlap another call."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ScheduleError(Exception):
    """No open interview window exists inside the search horizon."""


@dataclass(frozen=True)
class BusyWindow:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class SlotRules:
    duration: timedelta
    zone: ZoneInfo
    day_start_hour: int
    day_end_hour: int
    weekdays: frozenset[int]
    lead: timedelta


def interview_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name.strip() or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def parse_weekdays(value: str) -> frozenset[int]:
    days: set[int] = set()
    for part in value.split(","):
        piece = part.strip()
        if piece.isdigit() and 0 <= int(piece) <= 6:
            days.add(int(piece))
    return frozenset(days or {0, 1, 2, 3, 4})


def aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def overlaps(start: datetime, end: datetime, busy: list[BusyWindow]) -> bool:
    """True when [start, end) shares any moment with a busy window."""
    slot_start = aware(start)
    slot_end = aware(end)
    for window in busy:
        if aware(window.end) <= aware(window.start):
            continue
        if slot_start < aware(window.end) and aware(window.start) < slot_end:
            return True
    return False


def next_slot(now: datetime, busy: list[BusyWindow], rules: SlotRules) -> tuple[datetime, datetime]:
    """Return the next weekday slot that starts on the grid and misses every busy window."""
    if rules.duration <= timedelta(0):
        raise ScheduleError("duration")
    if rules.day_start_hour < 0 or rules.day_end_hour > 23 or rules.day_start_hour >= rules.day_end_hour:
        raise ScheduleError("hours")
    earliest = aware(now) + rules.lead
    day = earliest.astimezone(rules.zone).date()
    for offset in range(21):
        current = day + timedelta(days=offset)
        if current.weekday() not in rules.weekdays:
            continue
        cursor = datetime.combine(current, time(rules.day_start_hour, 0), tzinfo=rules.zone)
        limit = datetime.combine(current, time(rules.day_end_hour, 0), tzinfo=rules.zone)
        while cursor + rules.duration <= limit:
            slot_end = cursor + rules.duration
            if cursor >= earliest.astimezone(rules.zone) and not overlaps(cursor, slot_end, busy):
                return aware(cursor), aware(slot_end)
            cursor = slot_end
    raise ScheduleError("full")


def format_schedule(start: datetime | None, end: datetime | None, zone: ZoneInfo) -> str:
    if start is None or end is None:
        return ""
    local_start = aware(start).astimezone(zone)
    local_end = aware(end).astimezone(zone)
    return (
        f"{local_start.strftime('%a')} {local_start.day} {local_start.strftime('%b')}, "
        f"{local_start.strftime('%H:%M')}–{local_end.strftime('%H:%M')} ({zone.key})"
    )


def format_schedule_sentence(start: datetime, end: datetime, zone: ZoneInfo) -> str:
    local_start = aware(start).astimezone(zone)
    local_end = aware(end).astimezone(zone)
    return (
        f"{local_start.strftime('%A')}, {local_start.day} {local_start.strftime('%B %Y')}, "
        f"{local_start.strftime('%H:%M')}–{local_end.strftime('%H:%M')} ({zone.key})"
    )
