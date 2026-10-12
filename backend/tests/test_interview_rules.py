from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.schemas.interview import OpenedSessionRead, SessionDetailRead
from app.services.interview_rules import (
    InterviewError,
    SessionClock,
    assert_own_voice,
    assert_recruiter,
    bind_ice_host,
    can_store_audio,
    copilot_cache_matches,
    end_clock,
    format_transcript,
    ice_servers,
    outbound_signal,
    start_clock,
)


def _clock(status: str = "invited") -> SessionClock:
    return SessionClock(status=status, consented_at=None, started_at=None, ended_at=None, processing_status="")


def test_start_requires_consent_and_is_idempotent() -> None:
    now = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    with pytest.raises(InterviewError) as missing:
        start_clock(_clock(), consent=False, now=now)
    assert missing.value.code == "CONSENT_REQUIRED"
    started = start_clock(_clock(), consent=True, now=now)
    assert started.status == "started"
    assert started.consented_at == now
    again = start_clock(started, consent=True, now=now.replace(hour=10))
    assert again.consented_at == now
    assert again.started_at == now


def test_end_waits_for_start_and_stays_ended() -> None:
    now = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
    with pytest.raises(InterviewError) as early:
        end_clock(_clock(), now=now)
    assert early.value.code == "SESSION_NOT_STARTED"
    started = start_clock(_clock(), consent=True, now=now)
    ended = end_clock(started, now=now)
    assert ended.status == "ended"
    assert ended.processing_status == "pending"
    assert end_clock(ended, now=now.replace(minute=45)) is ended


def test_audio_is_stored_only_after_the_candidate_starts() -> None:
    assert can_store_audio("invited") is False
    assert can_store_audio("started") is True
    assert can_store_audio("ended") is False


def test_each_side_sends_only_its_own_voice() -> None:
    assert assert_own_voice("candidate", "candidate") == "candidate"
    with pytest.raises(InterviewError):
        assert_own_voice("candidate", "recruiter")
    with pytest.raises(InterviewError):
        assert_recruiter("candidate")


def test_turn_host_follows_the_browser_while_public_stun_stays() -> None:
    settings = Settings(
        _env_file=None,
        stun_urls="stun:stun.l.google.com:19302",
        turn_url="turn:localhost:3478",
        turn_username="sift",
        turn_password="sift-turn",
    )
    servers = ice_servers(settings)
    bound = bind_ice_host(servers, "203.0.113.10")
    assert bound[0]["urls"] == "stun:stun.l.google.com:19302"
    assert bound[1]["urls"] == "turn:203.0.113.10:3478"
    assert bound[1]["credential"] == "sift-turn"
    assert bind_ice_host(servers, "localhost")[1]["urls"] == "turn:localhost:3478"


def test_signaling_drops_unknown_and_oversized_payloads() -> None:
    assert outbound_signal("recruiter", {"type": "auth", "token": "secret"}) is None
    huge = {"type": "offer", "sdp": {"sdp": "x" * 100_001}}
    assert outbound_signal("recruiter", huge) is None
    offer = outbound_signal("candidate", {"type": "offer", "sdp": {"type": "offer", "sdp": "v=0"}})
    assert offer is not None
    assert offer["from"] == "candidate"


def test_transcript_lines_name_the_speaker() -> None:
    text = format_transcript([("candidate", 0.0, 5.0, "I built a FastAPI service.")])
    assert text == "candidate [0.0-5.0]: I built a FastAPI service."


def test_copilot_cache_waits_for_the_first_result() -> None:
    assert copilot_cache_matches(-1, 0) is False
    assert copilot_cache_matches(0, 0) is True
    assert copilot_cache_matches(1, 2) is False


def test_guest_payloads_do_not_include_transcript_or_scores() -> None:
    assert "transcript" not in OpenedSessionRead.model_fields
    assert "aggregate_score" not in SessionDetailRead.model_fields
    assert "summary" not in SessionDetailRead.model_fields
