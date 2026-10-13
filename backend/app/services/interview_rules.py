import json
from dataclasses import dataclass
from datetime import datetime

from app.core.config import Settings


class InterviewError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class SessionClock:
    status: str
    consented_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    processing_status: str


def start_clock(clock: SessionClock, *, consent: bool, now: datetime) -> SessionClock:
    if not consent:
        raise InterviewError("CONSENT_REQUIRED", "Consent is required before the interview starts.", 400)
    if clock.status == "ended":
        raise InterviewError("SESSION_ENDED", "This interview has already ended.", 409)
    if clock.status not in {"invited", "started"}:
        raise InterviewError("SESSION_NOT_FOUND", "This interview session is not available.", 404)
    return SessionClock(
        status="started",
        consented_at=clock.consented_at or now,
        started_at=clock.started_at or now,
        ended_at=None,
        processing_status=clock.processing_status,
    )


def end_clock(clock: SessionClock, *, now: datetime) -> SessionClock:
    if clock.status == "ended":
        return clock
    if clock.status != "started":
        raise InterviewError("SESSION_NOT_STARTED", "The interview has not started.", 409)
    return SessionClock(
        status="ended",
        consented_at=clock.consented_at,
        started_at=clock.started_at,
        ended_at=now,
        processing_status="pending",
    )


def end_for_role(role: str, clock: SessionClock, *, now: datetime) -> SessionClock:
    """Only the recruiter can close the interview. A guest leaving does not."""
    assert_recruiter(role)
    return end_clock(clock, now=now)


def can_store_audio(status: str) -> bool:
    return status == "started"


def assert_recruiter(role: str) -> None:
    if role != "recruiter":
        raise InterviewError("INTERVIEW_FORBIDDEN", "This view is only available to the recruiter.", 403)


def assert_own_voice(role: str, speaker: str) -> str:
    expected = {"candidate": "candidate", "recruiter": "recruiter"}.get(role)
    if expected is None or speaker != expected:
        raise InterviewError("INTERVIEW_FORBIDDEN", "Audio must be labeled as your own voice.", 403)
    return speaker


def chunk_window(start: object, end: object) -> tuple[float, float]:
    try:
        start_value = float(start)
        end_value = float(end)
    except (TypeError, ValueError) as exc:
        raise InterviewError("AUDIO_CHUNK_INVALID", "Audio chunk timing is not valid.", 400) from exc
    if end_value < start_value or end_value - start_value > 30:
        raise InterviewError("AUDIO_CHUNK_INVALID", "Audio chunk timing is not valid.", 400)
    return start_value, end_value


def copilot_cache_matches(stored_count: int, segment_count: int) -> bool:
    return stored_count >= 0 and stored_count == segment_count


def ice_servers(settings: Settings) -> list[dict[str, str]]:
    servers: list[dict[str, str]] = []
    for url in settings.stun_urls.split(","):
        cleaned = url.strip()
        if cleaned:
            servers.append({"urls": cleaned})
    turn = settings.turn_url.strip()
    if turn:
        entry = {"urls": turn}
        username = settings.turn_username.strip()
        password = settings.turn_password.strip()
        if username and password:
            entry["username"] = username
            entry["credential"] = password
        servers.append(entry)
    return servers


def bind_ice_host(servers: list[dict[str, str]], host: str) -> list[dict[str, str]]:
    """Point localhost relays at the host the browser actually called."""
    if host in {"", "localhost", "127.0.0.1"}:
        return servers
    bound: list[dict[str, str]] = []
    for server in servers:
        urls = server["urls"]
        for source, target in (
            ("turn:localhost", f"turn:{host}"),
            ("turn:127.0.0.1", f"turn:{host}"),
            ("stun:localhost", f"stun:{host}"),
            ("stun:127.0.0.1", f"stun:{host}"),
        ):
            urls = urls.replace(source, target)
        bound.append({**server, "urls": urls})
    return bound


def outbound_signal(role: str, message: dict[str, object]) -> dict[str, object] | None:
    kind = message.get("type")
    if kind in {"offer", "answer"}:
        sdp = message.get("sdp")
        if not isinstance(sdp, dict) or len(json.dumps(sdp)) > 100_000:
            return None
        return {"type": kind, "from": role, "sdp": sdp}
    if kind == "ice":
        candidate = message.get("candidate")
        if not isinstance(candidate, dict) or len(json.dumps(candidate)) > 8_000:
            return None
        return {"type": "ice", "from": role, "candidate": candidate}
    if kind == "bye":
        return {"type": "bye", "from": role}
    return None


def format_transcript(segments: list[tuple[str, float, float, str]]) -> str:
    return "\n".join(f"{speaker} [{start:.1f}-{end:.1f}]: {text}" for speaker, start, end, text in segments)
