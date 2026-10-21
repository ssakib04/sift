from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.schedule import BusyWindow, ScheduleError, SlotRules, next_slot, overlaps

ZONE = ZoneInfo("Asia/Dhaka")
RULES = SlotRules(
    duration=timedelta(minutes=45),
    zone=ZONE,
    day_start_hour=10,
    day_end_hour=17,
    weekdays=frozenset({0, 1, 2, 3, 4}),
    lead=timedelta(0),
)


def test_touching_windows_do_not_overlap() -> None:
    start = datetime(2026, 10, 21, 4, 0, tzinfo=UTC)
    middle = datetime(2026, 10, 21, 4, 45, tzinfo=UTC)
    end = datetime(2026, 10, 21, 5, 30, tzinfo=UTC)
    assert overlaps(start, middle, [BusyWindow(middle, end)]) is False
    assert overlaps(start, middle + timedelta(minutes=1), [BusyWindow(middle, end)]) is True


def test_successive_slots_meet_without_overlapping() -> None:
    now = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)
    first_start, first_end = next_slot(now, [], RULES)
    second_start, second_end = next_slot(now, [BusyWindow(first_start, first_end)], RULES)
    assert first_start == datetime(2026, 10, 21, 4, 0, tzinfo=UTC)
    assert first_end == second_start
    assert second_end == datetime(2026, 10, 21, 5, 30, tzinfo=UTC)
    assert overlaps(first_start, first_end, [BusyWindow(second_start, second_end)]) is False


def test_a_partial_block_skips_every_slot_it_touches() -> None:
    now = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)
    blocked = BusyWindow(
        datetime(2026, 10, 21, 4, 15, tzinfo=UTC),
        datetime(2026, 10, 21, 5, 0, tzinfo=UTC),
    )
    start, end = next_slot(now, [blocked], RULES)
    assert start == datetime(2026, 10, 21, 5, 30, tzinfo=UTC)
    assert end == datetime(2026, 10, 21, 6, 15, tzinfo=UTC)


def test_weekend_moves_the_call_to_monday() -> None:
    now = datetime(2026, 10, 24, 2, 0, tzinfo=UTC)
    start, _end = next_slot(now, [], RULES)
    local = start.astimezone(ZONE)
    assert local.weekday() == 0
    assert local.hour == 10
    assert local.day == 26


def test_lead_time_skips_slots_that_start_too_soon() -> None:
    now = datetime(2026, 10, 21, 3, 31, tzinfo=UTC)
    rules = SlotRules(
        duration=RULES.duration,
        zone=ZONE,
        day_start_hour=10,
        day_end_hour=17,
        weekdays=RULES.weekdays,
        lead=timedelta(hours=2),
    )
    start, _end = next_slot(now, [], rules)
    assert start.astimezone(ZONE).strftime("%H:%M") == "12:15"


def test_a_window_shorter_than_the_interview_has_no_slot() -> None:
    rules = SlotRules(
        duration=timedelta(minutes=45),
        zone=ZONE,
        day_start_hour=10,
        day_end_hour=10,
        weekdays=RULES.weekdays,
        lead=timedelta(0),
    )
    with pytest.raises(ScheduleError):
        next_slot(datetime(2026, 10, 21, 2, 0, tzinfo=UTC), [], rules)
