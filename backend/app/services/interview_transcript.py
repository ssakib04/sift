from datetime import datetime
from enum import Enum


class TranscriptWrite(Enum):
    IGNORE = "ignore"
    UPDATE = "update"
    INSERT = "insert"


def accepted_speaker(identity: str) -> str | None:
    """The transcriber only records the two people in the interview."""
    if identity in {"recruiter", "candidate"}:
        return identity
    return None


def spoken_window(text: str, *, started_at: datetime, now: datetime) -> tuple[float, float]:
    """Place a finished sentence on the interview clock."""
    words = max(1, len(text.split()))
    end = max(0.0, (now - started_at).total_seconds())
    start = max(0.0, end - max(1.0, words * 0.4))
    return start, end


def transcript_write(
    *,
    open_text: str | None,
    latest_final_text: str | None,
    text: str,
    final: bool,
) -> tuple[TranscriptWrite, str]:
    """Decide whether a spoken update replaces the open line, adds one, or is already stored."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return TranscriptWrite.IGNORE, ""
    if open_text is not None:
        return TranscriptWrite.UPDATE, cleaned
    if final and latest_final_text == cleaned:
        return TranscriptWrite.IGNORE, cleaned
    return TranscriptWrite.INSERT, cleaned
