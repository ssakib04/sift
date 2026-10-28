import uuid
from datetime import UTC, datetime, timedelta

from livekit.api import CreateAgentDispatchRequest

from app.services.interview_livekit import TRANSCRIBER_AGENT_NAME, listener_already_sent, transcriber_dispatch
from app.services.interview_practice import is_practice_job, practice_guest_url
from app.models.candidate import TranscriptSegment
from app.services.interview_sessions import visible_transcript
from app.services.interview_transcript import (
    TranscriptWrite,
    accepted_speaker,
    spoken_window,
    transcript_notice,
    transcript_write,
)


def test_a_live_notice_keeps_the_words_that_have_arrived() -> None:
    notice = transcript_notice("candidate", "  I   built  ", final=False)
    assert notice == {"speaker": "candidate", "text": "I built", "final": False}


def test_only_the_two_interview_participants_are_transcribed() -> None:
    assert accepted_speaker("recruiter") == "recruiter"
    assert accepted_speaker("candidate") == "candidate"
    assert accepted_speaker("agent-AJ_123") is None


def test_a_sentence_is_placed_before_the_moment_it_finished() -> None:
    started = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)
    now = started + timedelta(seconds=12)
    start, end = spoken_window("I built a FastAPI service for hiring.", started_at=started, now=now)
    assert end == 12
    assert 0 <= start < end


def test_a_listener_already_in_the_room_is_not_sent_again() -> None:
    assert listener_already_sent(["sift-transcriber"], "sift-transcriber")
    assert not listener_already_sent([], "sift-transcriber")
    assert not listener_already_sent(["sift-interviewer"], "sift-transcriber")


def test_transcriber_dispatch_targets_the_interview_room() -> None:
    request = transcriber_dispatch("session-1")
    assert isinstance(request, CreateAgentDispatchRequest)
    assert request.agent_name == TRANSCRIBER_AGENT_NAME
    assert request.room == "session-1"
    assert request.metadata == "session-1"


def test_speech_updates_the_open_line_until_the_sentence_finishes() -> None:
    action, text = transcript_write(open_text=None, latest_final_text=None, text="Hel", final=False)
    assert action is TranscriptWrite.INSERT
    assert text == "Hel"
    action, text = transcript_write(open_text="Hel", latest_final_text=None, text="Hello there", final=False)
    assert action is TranscriptWrite.UPDATE
    assert text == "Hello there"
    action, text = transcript_write(open_text="Hello there", latest_final_text=None, text="Hello there.", final=True)
    assert action is TranscriptWrite.UPDATE
    assert text == "Hello there."


def test_a_finished_sentence_is_not_stored_twice() -> None:
    action, _text = transcript_write(
        open_text=None,
        latest_final_text="Hello there.",
        text="Hello there.",
        final=True,
    )
    assert action is TranscriptWrite.IGNORE


def test_the_next_sentence_starts_a_new_line() -> None:
    action, text = transcript_write(open_text=None, latest_final_text="Hello there.", text="I", final=False)
    assert action is TranscriptWrite.INSERT
    assert text == "I"


def test_blank_speech_is_ignored() -> None:
    action, text = transcript_write(open_text=None, latest_final_text=None, text="   ", final=True)
    assert action is TranscriptWrite.IGNORE
    assert text == ""


def test_a_profile_transcript_keeps_settled_lines_only() -> None:
    session_id = uuid.uuid4()
    now = datetime(2026, 10, 28, tzinfo=UTC)

    def line(text: str, *, final: bool) -> TranscriptSegment:
        return TranscriptSegment(
            id=uuid.uuid4(),
            session_id=session_id,
            speaker="candidate",
            start_time=0,
            end_time=1,
            text=text,
            confidence=1,
            is_final=final,
            created_at=now,
        )

    kept = visible_transcript([line("  I built the API.  ", final=True), line("uhm", final=False), line("   ", final=True)])
    assert [segment.text for segment in kept] == ["  I built the API.  "]


def test_practice_guest_link_uses_the_public_site() -> None:
    assert practice_guest_url("https://interviews.example/", "abc") == "https://interviews.example/invite/abc"
    assert practice_guest_url("", "abc") == "http://localhost:3000/invite/abc"
    assert is_practice_job("sift-practice-interview")
    assert not is_practice_job("Backend Engineer")
